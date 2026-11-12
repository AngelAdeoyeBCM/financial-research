# Classification instructions protocol

Rules for writing `classification.instructions` in `config/taxonomies/*.yaml`.

- Always a YAML list of strings, never a single prose block.
- One instruction per bullet; each bullet states exactly one rule.
- State scope/filtering rules (what counts as in-scope content) before
  labeling-mechanics rules (multi-label, specificity, empty handling).
- Keep each bullet a short, imperative sentence.
- Do not restate `disambiguation` guidance here; label-vs-label distinctions
  belong in the `disambiguation` section, not in `instructions`.
- When revising an existing taxonomy, keep the existing bullet order stable
  except when inserting a new rule next to the rule it most relates to.
