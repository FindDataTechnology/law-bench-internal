# prompt-compare-web Delta — async-compare-run-identity

## MODIFIED Requirements

### Requirement: Compare Run Instrumentation
While a compare run is in flight after submit, the UI SHALL show an elapsed-time indicator that updates without page reload, SHALL keep the active-locale status message visible, SHALL offer a cancel control that aborts the client's wait for the response and returns the form to an editable state, and SHALL confirm that the form configuration was preserved. The submit SHALL use the API's async mode: the response returns a compare id immediately, and the UI SHALL poll the compare's status until it is no longer `running`, then navigate to the result on `done` or show the error inline on `failed`. The compare list SHALL render `running` compares with a visible status mark so an in-flight run survives a page refresh, and the form SHALL surface the most recent still-`running` compare as a one-click link instead of letting the operator orphan it. After a failed or cancelled submit, a resubmission of an identical configuration SHALL require explicit confirmation before starting, to prevent accidental duplicate runs; when an identical configuration is already `running` on the server, the confirmation SHALL offer to open that run instead of starting a new one. Aborting the client wait SHALL NOT claim to stop server-side work — and with async identity it no longer orphans it.

#### Scenario: elapsed time is visible during the run
- **WHEN** a compare run is in flight
- **THEN** the status area shows an updating elapsed-time indicator (e.g. 已运行 0:42) alongside the localized running message

#### Scenario: cancel returns the form to editable state
- **WHEN** the user activates the cancel control during a run
- **THEN** the client stops polling, the submit control re-enables, and a localized note confirms the configuration is preserved
- **AND** the note links to the still-running compare instead of merely admitting the server may still be running

#### Scenario: refresh mid-run reconnects to the run
- **WHEN** the user refreshes or leaves during an in-flight run and returns to `/compare` or `/compare/new`
- **THEN** the still-`running` compare is visible with a status mark and opens by one click

#### Scenario: duplicate resubmission requires confirmation
- **WHEN** a previous submit failed or was cancelled and the user submits the identical configuration again
- **THEN** the UI asks for explicit confirmation before starting the run
- **AND** a changed configuration submits without the extra confirmation
- **AND** when an identical configuration is already `running` on the server, the confirmation offers to open that running compare instead of starting a new one

#### Scenario: failure surfaces inline with retry
- **WHEN** a polled compare ends with `status: "failed"`
- **THEN** the form shows the localized error inline, re-enables submit, and preserves the configuration for retry
