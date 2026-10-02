# AIL development instructions for AI agents

Read `docs/AI_GUIDE.md` for graph generation and `docs/SPEC.md` for language
semantics. The current graph format is version 1; implementation version is 0.1.1.

Keep source JSON graphs as the source of truth. Do not repair generated assembly
instead of the graph or suppress verifier diagnostics to make a program compile.

For compiler changes, update verifier, interpreter, x86 backend, schema and
specification as needed. For installation changes, run the lifecycle tests under
temporary prefixes. Tests must not use the user's default installation prefix.

Required check: `python3 -m unittest discover -s tests -v`.
If examples/schema change, regenerate them with the corresponding tools and check
the diff. A source release must be built from a clean tracked git checkout.

Never report GitHub CI or publication as completed unless it actually ran.
