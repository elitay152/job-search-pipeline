"""Plan document organization using eligible facts, without creating new career claims."""
from .review import group_key
from .baseline import employment_baseline


def build_composition_plan(career, selected):
    selected = set(selected)
    roles = {r.id: r for r in career.employments}
    sections = {}
    anchors = {'education': [], 'publication': [], 'project': [], 'skill': []}
    for e in career.evidence:
        if not e.eligible or e.id not in selected:
            continue
        if e.kind != 'experience':
            anchors[e.kind].append(e.id)
            continue
        key = group_key(e)
        jobs = [roles[i] for i in e.employment_ids]
        employers = sorted({j.employer for j in jobs} or ({e.employer} if e.employer else set()))
        section = sections.setdefault(key, {'employment_ids': e.employment_ids, 'employers': employers,
            'latest_start': max((str(j.start) for j in jobs), default=str(e.start or '')),
            'requires_placement_clarification': len(employers) != 1,
            'themes': {}, 'evidence_ids': []})
        section['evidence_ids'].append(e.id)
        section['themes'].setdefault(e.project, []).append(e.id)
    ordered = sorted(sections.values(), key=lambda s:s['latest_start'], reverse=True)
    for section in ordered:
        section['themes'] = [{'topic': topic, 'evidence_ids': ids} for topic, ids in section['themes'].items()]
        section['target_bullets'] = min(len(section['evidence_ids']), career.presentation.minimum_recent_bullets)
    return {'version': 'composition-v2', 'employment_baseline': employment_baseline(career), 'experience_sections': ordered, 'section_anchors': anchors,
        'resume_instructions': [
            'Saved employment_baseline jobs define immutable headers and chronology, including jobs with no selected bullets. Tailor only supported bullet content within its evidence-defined scope. Shared-role evidence remains shared; do not assign it to one job or duplicate it. Use the ordered role sections. Do not combine different employers into one experience heading.',
            'Themes are candidate groupings, not proof of causality. Combine facts only when sources support their relationship.',
            'Compose complete action-and-context bullets; include outcomes only when linked evidence supports them.',
            'Preserve ownership, metric qualifiers and dates. Use readable number formatting without changing values or units.',
            'Do not assign evidence marked requires_placement_clarification to a guessed employer; surface a clarification.',
            'Do not force a target count by repetition or invention. Keep education and publications in their own sections.'],
        'cover_letter_paragraphs': [
            {'purpose': 'Opening', 'instruction': 'Connect the named role to the strongest supported relevant experience. Use company/job names only if supplied.'},
            {'purpose': 'Relevant example', 'instruction': 'Explain one coherent supported project: personal actions, technical context and a supported result where available.'},
            {'purpose': 'Contribution', 'instruction': 'Connect another supported capability to a stated job responsibility. Do not invent motivation, company facts, or promises of results. The renderer supplies the closing courtesy; do not generate a separate closing paragraph.'}],
        'provenance_instruction': 'Every factual passage retains its supporting evidence IDs. A plan is organization guidance, never additional factual evidence.'}
