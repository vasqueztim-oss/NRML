# NRML

A news-first AI newsroom for everyday people.

## Agent prompts

Each newsroom role is a system prompt in `prompts/`. A story moves through them in this order:

1. `wire_desk.md`: clusters and labels the raw wire
2. `assignment_editor.md`: picks what the edition covers
3. `beat_reporter.md`: writes the news section
4. `fact_checker.md`: checks every claim against its source
5. `standards_editor.md`: checks tone, framing, and fairness
6. `policy_desk.md`: researches progressive options when there's a policy angle
7. `columnist.md`: Norm, who writes the take box
8. `format_desk.md`: packages approved stories for email, blog, and video

Every prompt expects `charter/rules.md` (and most expect `charter/where_we_stand.md`) to be appended below it.
