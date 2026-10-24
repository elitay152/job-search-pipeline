import argparse
import json
import os
from pathlib import Path
from pydantic import ValidationError
from .models import Career, Settings
from .store import Store
from .pipeline import run
from .export import approve, export

def main():
    p = argparse.ArgumentParser(description='Evidence-grounded application tailoring')
    p.add_argument('--db', default='local/pipeline.sqlite')
    sub = p.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run')
    r.add_argument('--jd', required=True)
    r.add_argument('--career', required=True)
    r.add_argument('--style', default='writing_style')
    r.add_argument('--generator', choices=['mock', 'anthropic'], default=os.getenv('GENERATOR_PROVIDER', 'mock'))
    r.add_argument('--reviewer', choices=['mock', 'anthropic'], default=os.getenv('REVIEWER_PROVIDER', 'mock'))
    r.add_argument('--max-revisions', type=int, default=2)
    for name in ('approve', 'export'):
        cmd = sub.add_parser(name)
        cmd.add_argument('run_id')
        cmd.add_argument('--career', required=True)
        if name == 'approve':
            cmd.add_argument('--reviewed', action='store_true')
        else:
            cmd.add_argument('--draft', action='store_true')
            cmd.add_argument('--output', default='artifacts')
    sub.add_parser('history')
    ev = sub.add_parser('evaluate')
    ev.add_argument('--output', default='local/evaluation.json')
    cal = sub.add_parser('calibrate')
    cal.add_argument('--samples', required=True)
    cal.add_argument('--output', required=True)
    args = p.parse_args()
    store = Store(args.db)
    try:
        if args.command == 'run':
            career = Career.model_validate_json(Path(args.career).read_text())
            settings = Settings(generator=args.generator, reviewer=args.reviewer, max_revisions=args.max_revisions,
                generator_model=os.getenv('GENERATOR_MODEL', 'claude-sonnet-4-5'),
                reviewer_model=os.getenv('REVIEWER_MODEL', 'claude-sonnet-4-5'),
                token_budget=int(os.getenv('TOKEN_BUDGET', '100000')),
                max_calls=int(os.getenv('CALL_BUDGET', '24')))
            m = run(Path(args.jd).read_text(), career, store, settings, args.style)
            print(json.dumps({k: m[k] for k in ('id','status','revision_count','stopping_reason','latency')}))
        elif args.command in ('approve', 'export'):
            career = Career.model_validate_json(Path(args.career).read_text())
            if args.command == 'approve':
                print(approve(store, args.run_id, career, args.reviewed)['status'])
            else:
                print('\n'.join(str(x) for x in export(store, args.run_id, career, args.output, args.draft)))
        elif args.command == 'history':
            print(json.dumps([{k: m[k] for k in ('id','created','status','latency','estimated_cost')} for m in store.history()], indent=2))
        elif args.command == 'evaluate':
            from .evaluation import evaluate
            print(json.dumps(evaluate(args.output), indent=2))
        else:
            from .style import calibrate
            calibrate(args.samples, args.output)
            print('Unapproved proposal saved; review and version it before use.')
    except ValidationError as exc:
        # Do not print Pydantic input values: they may contain private career text.
        details = [{'field': '.'.join(str(x) for x in e['loc']), 'type': e['type']} for e in exc.errors(include_input=False)]
        p.exit(1, 'Validation failed: ' + json.dumps(details) + '\n')
    except Exception as exc:
        p.exit(1, f'{type(exc).__name__}: operation failed; inspect local run stages and configuration.\n')

if __name__ == '__main__':
    main()
