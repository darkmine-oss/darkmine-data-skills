# TRK-372: Remove personal filesystem paths

## Intent

Keep the GSWA converter examples portable and prevent local usernames and run
directories from being published with the skill.

## Changes

- Replace absolute source paths with `path/to/...` placeholders.
- Scan the complete skill directory for Unix and Windows user-profile paths.
- Commit only the privacy edits, leaving the existing assay/provenance work
  uncommitted and untouched.

## Verification

- Run the personal-path scan over the skill directory.
- Review the staged diff independently from the existing working-tree diff.
