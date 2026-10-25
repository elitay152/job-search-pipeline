import argparse
import json
import os
from pathlib import Path
from pydantic import ValidationError
from .models import Career, Settings, Packet
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
    r.add_argument('--resume-only', action='store_true', help='Omit cover-letter generation and export')
    r.add_argument('--company', default='')
    r.add_argument('--role', default='')
    r.add_argument('--style', default='writing_style')
    r.add_argument('--generator', choices=['mock', 'anthropic', 'openai'], default=os.getenv('GENERATOR_PROVIDER', 'mock'))
    r.add_argument('--reviewer', choices=['mock', 'anthropic', 'openai'], default=os.getenv('REVIEWER_PROVIDER', 'mock'))
    r.add_argument('--factual-mode', choices=['strict','model_reviewed'], default=None)
    r.add_argument('--seed-packet', help='Review and revise an existing structured packet, without bypassing gates')
    r.add_argument('--generator-model', default=os.getenv('GENERATOR_MODEL'))
    r.add_argument('--reviewer-model', default=os.getenv('REVIEWER_MODEL'))
    r.add_argument('--report', help='Write a private Markdown reviewer report')
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
    ready = sub.add_parser('check-provider')
    ready.add_argument('--provider', choices=['mock', 'openai', 'anthropic'], required=True)
    ready.add_argument('--model', required=True)
    ready.add_argument('--role', choices=['generator', 'reviewer'], default='generator')
    layout = sub.add_parser('layout')
    layout.add_argument('run_id')
    layout.add_argument('--draft', action='store_true')
    layout.add_argument('--output', default='artifacts')
    inspect = sub.add_parser('inspect')
    inspect.add_argument('run_id')
    inspect.add_argument('--output', required=True)
    imp = sub.add_parser('import-intake')
    imp.add_argument('--intake', required=True)
    imp.add_argument('--output', required=True)
    ev = sub.add_parser('evaluate')
    ev.add_argument('--output', default='local/evaluation.json')
    cal = sub.add_parser('calibrate')
    cal.add_argument('--samples', required=True)
    cal.add_argument('--output', required=True)
    args = p.parse_args()
    store = Store(args.db)
    try:
        if args.command == 'check-provider':
            from .readiness import check_provider
            result = check_provider(args.provider, args.model, args.role)
            print(json.dumps(result))
            if result['status'] != 'passed':
                p.exit(1)
        elif args.command == 'layout':
            from .export import export_pdf
            paths = export(store, args.run_id, store.career_snapshot(args.run_id), args.output, args.draft)
            print(json.dumps(export_pdf(store, args.run_id, paths)))
        elif args.command == 'run':
            career = Career.model_validate_json(Path(args.career).read_text(encoding='utf-8'))
            settings = Settings(generator=args.generator, reviewer=args.reviewer, max_revisions=args.max_revisions, include_cover_letter=not args.resume_only,
                factual_mode=args.factual_mode or ('model_reviewed' if args.reviewer != 'mock' else 'strict'),
                generator_model=args.generator_model,
                reviewer_model=args.reviewer_model,
                token_budget=int(os.getenv('TOKEN_BUDGET', '250000')),
                max_calls=int(os.getenv('CALL_BUDGET', '48')))
            seed = Packet.model_validate_json(Path(args.seed_packet).read_text(encoding='utf-8')) if args.seed_packet else None
            m = run(Path(args.jd).read_text(encoding='utf-8'), career, store, settings, args.style, seed_packet=seed, application={'company': args.company, 'role': args.role})
            if args.report:
                from .report import review_report
                Path(args.report).parent.mkdir(parents=True, exist_ok=True)
                Path(args.report).write_text(review_report(m, career), encoding='utf-8')
            print(json.dumps({k: m[k] for k in ('id','status','revision_count','stopping_reason','latency')}))
        elif args.command in ('approve', 'export'):
            career = Career.model_validate_json(Path(args.career).read_text(encoding='utf-8'))
            if args.command == 'approve':
                print(approve(store, args.run_id, career, args.reviewed)['status'])
            else:
                print('\n'.join(str(x) for x in export(store, args.run_id, career, args.output, args.draft)))
        elif args.command == 'import-intake':
            from .intake import import_intake
            result = import_intake(args.intake, args.output)
            print(json.dumps({'eligible': sum(e.eligible for e in result.evidence), 'records': len(result.evidence)}))
        elif args.command == 'inspect':
            from .report import review_report
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(review_report(store.get(args.run_id), store.career_snapshot(args.run_id)), encoding='utf-8')
            print('Private review report saved')
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
