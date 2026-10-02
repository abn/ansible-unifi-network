# Comment rules

Extends `AGENTS.md`. Applies to every comment in the repository, in any
language: `#`, `//`, `;`, and `<!-- -->`.

## What a comment is for

A comment earns its place by doing one of two things:

1. **Explaining a non-obvious constraint.** Why the code cannot be the obvious
   thing. A protocol requirement, a tool limitation, a decision that looks wrong
   until you know the reason.
2. **Saying something the code cannot say.** A unit, an invariant, or a hazard
   that is invisible in the syntax.

If a comment would be unchanged by a refactor of the line it sits on, it is
saying nothing. Delete it.

## Forbidden

**Narrative.** A comment describing how something came to be, or addressed to a
reader rather than about the code.

- History: "changed from X", "used to be", "no longer", "as of now".
- Process: "verified empirically", "turns out", "initially", "in the first
  version".
- First person. `I`, `we`, `my`, `our`. A comment is about the code, not about
  the author.
- Self-narration: "note that we had to", "this is how we found out", "this was
  broken because".

**The obvious.** Restating the code, or restating a convention the reader already
knows.

- `# increment the counter` above `i += 1`.
- `# returns the result` above `return result`.
- `# Loop over the devices` above `for device in devices:`.
- Section banners that only label what the filename already says.

**A postmortem.** A comment that reads as a record of debugging is almost always
three separate facts about the code, and each of them belongs in the code or in
the commit message instead. A comment that names the failure it prevents is good;
a comment that narrates finding that failure is not.

## Allowed

- SPDX and licence identifiers, which are declarations rather than prose.
- A short label where a list would otherwise be opaque, such as naming the
  protocol or specification a block implements.
- A pointer to the authoritative source, including a URL.
- A warning about a consequence, such as a call that breaks live connections or a
  tool that reads a different directory than a reader would expect.
- Explaining why a guard exists, and why it refuses rather than proceeding.
- Naming a version, digest, or specification a value came from, because that is
  not derivable from the file and goes stale in a way a reader cannot check.

## Test for a comment

Ask: if the next line were deleted, would this comment leave the reader worse off?

If the answer is no, the comment is decoration.

Then ask: does the comment describe the code as it is now, or as it was? If it
describes the past, rewrite it or delete it. A future reader with no context of
the change must find every comment accurate and self-contained.

## Length

A comment that needs a blank comment line inside it is usually a document that
belongs in `docs/`, or is three comments that should be three separate facts.
One paragraph is the practical limit. If a second paragraph is genuinely needed,
the first one is carrying weight it could carry alone.

## Prose is not a comment

These rules govern comments in code and configuration. Prose in `docs/` and
`README.md` is written to readers and may use the first person freely.

Prose does carry the related ban on marketing language, throat-clearing and
restating the code, and the ban on claims that rot, such as counts, dates and
"currently the case" assertions. Those are in
[documentation.md](documentation.md).
