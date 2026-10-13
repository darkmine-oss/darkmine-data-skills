# Structural observations: single-table preserving conversion

Reuse the shared attribute-expansion API. Retain one parent row, original
bounds, source structure/collar keys and every attribute record. Use depth=from
for the point-view plotting anchor; no end-depth inference. Explicit measured
angle aliases only; plane/calculated/local measurements remain distinct JSON.
Numeric parse failures remain JSON evidence and manifest diagnostics, while
finite out-of-range angles remain for QAQC. Source code labels stay undecoded.
Update structural plotting skill/code docs to state the start-depth convention.
This extends preserving mode; the default frontend conversion retains its
separate existing cleanup behavior. Project-sized, in-memory EAV processing.

Validation: original-row and attribute coverage, null/absent end depths, repeated
public hole identifiers, partial pairs, conflicts, parse failures and invalid
source identities. Branch development depends on the unmerged attribute API.
