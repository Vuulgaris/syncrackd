# Contributing

Contributions are welcome. The project is run the way the Linux kernel is: one maintainer (@Vuulgaris) decides what goes into `main`, and every change, the maintainer's own included, arrives as a pull request that gets reviewed. A good change can still be turned down because it does not fit where the project is going. Ask in Discussions before building anything big.

## The rules that are never bent

1. **No Elektron firmware, ever.** No `.syx`, no extracted sections, no disassembly listings, no byte runs copied from the OS, no screenshots of renders made by Elektron's code, in code, docs, tests, issues or PRs. Addresses, sizes and hashes are fine; the bytes are not. A PR that carries any is closed and its branch deleted.
2. **Only sections 3 and 7 are patched.** The bootloader and updater are never touched; `tools/fw.py` enforces it and a build must fail hard otherwise.
3. **Exact OS builds only.** Every patch site checks the stock bytes it expects, and the image may differ from the official one only inside declared regions. Stock bytes in source are sealed: write the hex, then run `python -m tools.seal FILE`, which turns it into `fw.sx("...")`, opened at build time with a key only the official file gives. `--check` must list nothing before a PR.
4. **Licenses.** Code may be copied only from MIT sources (`third_party/`). Modded-Cycles has no license: read it, never copy it. digikit is GPL-2.0: an outside tool only, never vendored.
5. **Verify, don't trust.** An address or behavior is confirmed in our own tooling before anything relies on it, and how it was confirmed goes in `docs/FINDINGS.md`. If it cannot be confirmed, say so there and do not build on it.
6. **Nothing talks to a unit.** No script in this repo sends anything to a Syntakt. Flashing is the user's own step.

## How a change is shaped

- **A feature is an image.** It builds on the newest image in the chain, its new code sits under its own `#ifdef` or in a new file (older images must still build to the same hashes), and it has its own test file, `tests/test_<image>.py`, showing it differs from the image before only in what it declares.
- **Which tests.** `make check IMAGE=x` runs your image's own test file. `make test` is the quick run (the tools, the emulator, the engine, and the release image's own file): run it before a PR. `make test-chain` runs every image's file (ten to twenty minutes): only if you changed source that older images are built from, and then say so in the PR. The tests need the official 1.42 file in `firmware/` and the cross-compiler; CI has neither, so it checks only the guard and that everything compiles.
- **Where stock's own routine can run in emulation, run it.** A stand-in shares your mistake.
- **A change to how a page looks:** `make screen` it and attach the PNG to the PR. (Only your own PR, and only because the screen is ours: if the render is mostly stock's page, describe it instead.)
- **One change per PR.** One feature or one fix. Small commits, each one building.
- **No em dash** in any file. Terse docs.

## Commits

- Subject line in the imperative, under 72 characters, prefixed with the area: `engine: fade a one-shot's end at full LEN`, `tools: hash the stock bytes in _expect`.
- A body that says why, and what was checked.
- **Signed off**: `git commit -s`. By signing off you certify the [Developer Certificate of Origin](https://developercertificate.org/): you wrote it, or have the right to send it under the project's license. Every commit, checked by CI.
- AI-assisted code is fine. You sign off for it, so you understand it and stand behind it.

## Pull requests

Fill in the template. It asks:

- which image it builds on, and the image it makes;
- the test file you ran and its result (`make check IMAGE=x`);
- **whether it ran on a unit**, and what you heard. "Not on a unit" is an honest answer; it just means it will not merge as working until someone runs it;
- the output image's SHA-256, so a tester can be sure they have your build.

The maintainer may rebase, squash, reword or split your commits before merging. Your authorship and sign-off are kept.

## Hardware reports

The most useful thing anyone with a Syntakt can do. Use the "Hardware report" issue form: the image's SHA-256, what you did, what you heard, and whether the unit went back to the official OS fine. Recordings help; never attach firmware.

## Not wanted

- PRs that support other OS versions without the hashes and checks to pin them.
- Reformatting or renaming sweeps.
- Features that need the user to install something on their computer to flash.
- Anything that sends to a unit from this repo.
