# GH-96: QA fixes for the skills + baselode

Tracks [darkmine-oss/baselode#96](https://github.com/darkmine-oss/baselode/issues/96).
The baselode half (validator checks, fix helpers, desurvey changes) ships in
baselode; this repo consumes them.

## Intent

Close the gaps a QA pass over a GSWA export found: the setup skill breaking
on Windows and on old Pythons, survey rows with null orientation passing
validation and silently dropping holes from the desurvey, no way to rebuild
those holes, and thousands of interleaved-campaign overlaps left for a person.

## Design

- `setup`: platform-aware venv interpreter path (`Scripts\python.exe` on
  Windows), probe every candidate interpreter's version before creating the
  venv and refuse anything below baselode's `requires-python`, probe the `py`
  launcher on Windows, and fall back to directory junctions when symlinks
  are refused.
- `drillhole-validate`: documents the new `survey_null_orientation` (error)
  and `survey_no_usable_stations` (warning) checks baselode now emits.
- `drillhole-fix`: two new fixes, `unusable-survey-rows` and
  `synthesise-collar-station` (with `--collar-azimuth-col` /
  `--collar-dip-col`), slotted before `normalize-azimuth` so the apply order
  is a dependency chain ending in `single-station-surveys`.  `--prefer-dataset`
  + `--dataset-col` turn on baselode's dataset-precedence overlap class.
- `drillhole-desurvey`: exposes `midpoint_tangential`; documents that every
  trace now starts at the collar.

## Verification

- `tests/test_setup_script.py` covers the interpreter path per platform and
  the version gate.
- `tests/test_apply_fixes_surveys.py` runs the fix script end to end over a
  temp project: unusable rows dropped, missing holes synthesised (collar
  orientation and vertical fallback), padded to `max_depth`, re-validated
  clean; overlaps resolved by dataset precedence.
- Requires baselode with the GH-96 changes (`pip install -e ../baselode/python`
  until the next release).
