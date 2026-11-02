# Notes and daily workflow

Use the vault's existing flat layout. Ordinary notes are root-level kebab-case
English filenames; human titles and content can be Russian. Do not migrate old
notes automatically. Links, tags and MOC provide navigation.

| Purpose | Content |
| --- | --- |
| Daily capture | Raw text, timestamp and source; no need to choose tags or a MOC |
| Knowledge (`zettel`) | One conclusion, applicability, reason, proof/date and source links |
| Project (`project`) | Goal, current state, constraints, blocker, next step and artifact links |
| Source (`source`) | Attributed original claims, origin and date |

New durable notes start as `seedling`. `status` describes maturity, not whether
work is pending or a claim has been retracted. Existing MOC notes are curated
navigation; do not mechanically maintain a second copy of every relationship.

## Knowledge body

```markdown
## Conclusion
One clear claim. Mark an unimplemented proposal explicitly.

## Applies when
Conditions and limits.

## Why
Reason and alternatives rejected.

## Verification
What was tested, when, and the result. State when unverified.

## Sources and links
Source URLs, repository artifacts and at least one existing [[note]].
```

Creation arguments include title, description, content, tags and optional moc.
The API writes the frontmatter. Preserve existing fields when updating. Dates
and versions carry an as-of date. Do not infer the truth of a claim from `updated`.

## Project card

```markdown
## Goal
The current desired outcome.

## Current state
What exists and what was verified, with a date.

## Constraints
Applicable constraints and links to decisions.

## Next step
One concrete action to resume.

## Blockers
Unresolved questions or required external input.

## Decisions and artifacts
Links to durable notes, source code and verification results.
```

Keep this card short: it is automatically recalled. Replace its state using the
revision from the read; do not append an endless session log to the card.

Morning: read the active card and choose today's outcome. During work: capture
raw ideas quickly; save verified decisions with reasons as they settle. Before
switching projects: update the card's proof and next step. Weekly: triage captures,
review stale claims and broken links. Show merge/delete/rename proposals before
applying them. Full graph checks belong to maintenance, not every capture.
