# API policy observatory

## Current evidence

Admin build and cache regressions pass; full legacy suite remains broken.

## Next product increment — planned

Repair the outdated backend suite, then expose a trace explaining cache, quota and policy decisions.

## Acceptance gate

One trace explains a cold request, cached response, stale refresh and denied request under tested policies.

A release also needs reproducible checks, useful empty/error states, keyboard/mobile review where applicable, and an inspectable example with appropriate data. Planned work above is not shipped functionality.
