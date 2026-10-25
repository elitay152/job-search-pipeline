import json
import re
from pathlib import Path

def calibrate(manifest_path, output):
    samples = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    eligible = [s for s in samples if s['authorship'] in ('user-authored', 'explicitly-user-approved')]
    if not eligible:
        raise ValueError('Select user-authored or explicitly approved professional samples')
    lengths = []
    for s in eligible:
        text = Path(s['path']).read_text(encoding='utf-8')
        lengths += [len(sentence.split()) for sentence in re.split(r'[.!?]+', text) if sentence.strip()]
    profile = json.loads(Path('writing_style/profile.json').read_text(encoding='utf-8'))
    profile.update(version='proposal-v1', approved=False,
        basis='Local sentence-length observations; other preferences remain neutral pending review',
        samples=[{'id': s['id'], 'authorship': s['authorship']} for s in eligible],
        observed_mean_sentence_words=round(sum(lengths)/max(len(lengths), 1), 1),
        calibration_example={'before': 'I was responsible for the development of a pipeline.',
                             'after': 'I developed a pipeline.', 'label': 'Synthetic illustration, not a career claim'})
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(json.dumps(profile, indent=2), encoding='utf-8')
    return profile
