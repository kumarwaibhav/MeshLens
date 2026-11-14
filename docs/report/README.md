# MeshLens illustrated report

- [Project report PDF](MeshLens_Project_Report.pdf)
- [Editable Word edition](MeshLens_Project_Report.docx)
- [GitHub-readable edition](../PROJECT_REPORT.md)
- [Longer technical manual](../PROJECT_DOCUMENTATION.md)

The 26-page report covers the reference source release `5f11b39`, reviewed on 14 November 2026. It includes 24 chapters plus the cover and reading guide. The report records the measured limitations rather than claiming independent production qualification.

## Rebuild

The documentation tools are separate from the model inference environment. Use a dedicated Python environment, Node.js 22 or newer, and LibreOffice for PDF conversion:

```bash
python -m venv .venv-docs
# Activate this environment using your operating system's normal command.
python -m pip install -r docs/report/requirements-docs.lock
npm ci --prefix docs/report
python docs/report/build_assets.py
node docs/report/render_assets.mjs
python docs/report/build_report.py --pdf
```

`build_report.py` without `--pdf` produces Word and Markdown. PDF conversion requires `soffice` or `libreoffice` on PATH. The lock records the documentation dependencies used for this edition. Numerical code, frozen models and evaluation are not modified by these builders.

Read the generated report and inspect every rendered page after content, font or layout changes. Recheck image captions, table wrapping, model roles, counts, CLI behavior, licensing and evidence dates. Current screenshots and their scope are described in [assets/README.md](../assets/README.md).

## Update policy

Treat the source release, benchmark counts, screenshots and audit dates as a linked evidence snapshot. Change these only when a new release has corresponding evidence. A new documentation commit also needs its own passing CI result; the recorded reference run belongs to `5f11b39`.
