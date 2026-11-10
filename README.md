# Darkwatch Darker VR

## DARKWATCH DARKER EDITION PC PORT BY LINKSSY2

The PC port and the 0.7.8 launcher foundation come from [Linkssy2’s Darkwatch: Darker Edition](https://github.com/linkssy2/DarkwatchDarkerEdition). See the [upstream 0.7.8 release notes](https://github.com/linkssy2/DarkwatchDarkerEdition/releases/tag/v0.7.8).

This repository includes the upstream 0.7.8 port source and a separate Windows VR launcher layer. The VR launcher opens a separately prepared VR installation. The local VR game runtime is based on 0.7.6. Launcher update checks target this VR repository and keep the installed runtime separate.

See [building](docs/BUILDING.md), [code map](docs/CODE_MAP.md) and [credits](CREDITS.md).

[Report a bug or issue](https://github.com/stevethetitan92/DarkwatchDarkerVR/issues/new?template=bug_report.yml).

Supply your own supported original Xbox disc. This is the maintained host integration and pinned SDK patch, not the original game source. Original game files, generated game C++, saves, caches and private gameplay captures are absent. The official runtime is built with `./scripts/build-xbexbe.ps1 -Release` after the initial dependency build described in BUILDING.md. Keep the Release profile for player packages; development-only code paths are not shipped features.

The existing 0.7 HD pack remains compatible and is not included in this source archive.

The VR launcher imports Spanish, French, German and Italian from a supported PAL PS2 disc. It also supports the optional Brazilian Portuguese text translation.

## PROJECT CREDITS

- **[TGP482 / XboxXBERecomp](https://github.com/TGP482/Xbox-XBERecomp)** — static recompilation toolchain and Direct3D 12 runtime.
- **[sp00nz / xboxrecomp](https://github.com/sp00nznet/xboxrecomp)** — earlier investigation and host foundation.
- **BitJager-dev and brandonsoto** — upstream testing and integration feedback.
- **HNNEWGAMES** — optional Brazilian Portuguese text adaptation.
- **Darkwatch’s original creators and rights holders**, and the contributors to **SDL3, Dear ImGui, toml++, Zydis/Zycore, Proton and Wine** — see [full credits and notices](CREDITS.md).
