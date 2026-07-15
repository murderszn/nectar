# Third-party inspiration & licenses

OpenCodeHarness is original code under the MIT License (see `LICENSE`).

It is **architecturally inspired** by two excellent MIT-licensed open-source agents.
We reviewed their public repositories and re-implemented a smaller, Python-native
tool surface suited to a Pollen-authenticated harness — we did **not** copy their
source trees wholesale.

## OpenCode

- Project: [OpenCode](https://opencode.ai) / [anomalyco/opencode](https://github.com/anomalyco/opencode) (and related `opencode-ai` lineage)
- License: MIT
- Ideas adopted at the *design* level:
  - Terminal-native coding agent loop
  - Tool-first workflow (read / edit / bash / search)
  - Build vs plan style agent modes
  - Model-agnostic provider layer

## Hermes Agent (Nous Research)

- Project: [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
- License: MIT  
  Copyright (c) 2025 Nous Research
- Ideas adopted at the *design* level:
  - Paginated `read_file` with line numbers and char guards
  - Surgical patch / string-replace edits
  - Workspace path discipline for file tools
  - Content + file search as first-class tools (rg when available)
  - Tool registry as the single dispatch surface

## Pollinations BYOP

- Device-authorization login for **Pollen** balance (`enter.pollinations.ai`)
- This is OpenCodeHarness’s primary product wrinkle: open coding agent UX +
  Pollen as login/payment, rather than a proprietary model subscription.

## Your obligations

If you distribute OpenCodeHarness, keep this notice and the project MIT license.
If you later vendor any *literal* third-party source files, add them under
`third_party/` with their original copyright headers.
