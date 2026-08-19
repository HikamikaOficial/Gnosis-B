# 00_SETUP — GNOSIS v0.3 / Nicol workstation

## Canonical project location

```text
C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi
```

This Windows path is the **single source of truth** for the friend's machine.

## Canonical external-repository location

```text
C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\external\repositories
```

Place the downloaded reference repositories there.

Claude does not depend on folder names: `scripts/inventory_repositories.py` resolves repositories by GitHub `origin`.

## Step 1 — Extract

The extracted root must be:

```text
C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi
```

## Step 2 — Put repositories here

```text
C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi\external\repositories
```

All original external repos remain read-only research sources.

## Step 3 — Bootstrap PowerShell

```powershell
Set-Location "C:\Users\nicol\Desktop\Claude Code Proyectos\GnosisAgentAi"
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-nicol.ps1
```

This creates the runtime structure, inventories registered repositories, runs the workstation doctor and runs the Memory Fabric doctor.

## Step 4 — Start Claude/Fable 5

```powershell
.\scripts\launch-gnosis-claude.ps1
```

Then send:

```text
Lee 01_START_HERE.md y ejecútalo completamente. No me hagas preguntas sobre decisiones técnicas reversibles. Prepara primero el entorno y el Memory Fabric M3+ZMem, verifica los recursos locales contra resources/repositories.json, investiga, decide, documenta, prueba, autocorrige y continúa.
```

## Windows optimization

Use current native Claude Code on Windows as the main interactive environment.

Install/update:
- Git for Windows;
- Claude Code;
- Codex CLI;
- Python 3.12+;
- uv;
- ripgrep.

WSL2 is optional for Linux-only tools and stronger sandbox experiments. Do not maintain a second editable copy of GNOSIS inside WSL.

## Before coding Gnosis

Claude MUST finish:
1. workstation doctor;
2. repository inventory;
3. M3 + ZMem installation/configuration;
4. Memory Fabric smoke test;
5. Tier-S resource audit;
6. initial ADRs.

No substantial kernel implementation before these gates.
