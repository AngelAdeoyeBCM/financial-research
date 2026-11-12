# Subject/body identity in SQLite

Use python -m src.pipeline --database data/research.sqlite3 to sync Outlook.
Inbox/all-time is the default. --since and --until are independently optional.

Sender does not affect deduplication. Receipt times must be within 24 hours
(inclusive) of the stored representative; UTC comparisons handle offsets and
midnight. Skipped copies do not extend the window. An indexed body_fingerprint identifies
matching source bodies; fuzzy normalized-subject matching then resolves candidates
to a canonical emails.fingerprint primary key. The subject threshold is 90%, with
numeric differences rejected. Distinct body content and matching reports
received more than 24 hours apart remain separate. Candidate occurrence
fingerprints include receipt time to prevent primary-key collisions across days.

EmailRepository applies the same matching rule to incremental and offline writes.
The first stored metadata remains canonical. Image-mode reprocessing updates the
same record. processed_emails records the committed canonical fingerprint/profile.
Failed runs roll back both data and processed state.

Dataframe writes require fingerprint and body_fingerprint from extraction.
Candidate hashes can differ for fuzzy subject variants; database storage resolves
them to a shared canonical fingerprint. iter_records()/to_dataframe() return those
stored canonical IDs.

migrate_fingerprints() upgrades older schemas using original source emails,
backs up the complete database, merges duplicates, and clears old processing
receipts. Sender never affects identity. Receipt time now bounds duplicate matching.
recover_from can name an earlier backup to reconsider previously merged
deliveries and restore any outside the window.
