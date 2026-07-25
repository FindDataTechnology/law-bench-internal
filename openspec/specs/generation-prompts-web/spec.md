# Generation Prompts Web Specification

## Purpose
Web management UI (HTML + JSON API) for generation prompts.
## Requirements
### Requirement: Browse Generation Prompts
The system SHALL present a list of all generation prompts, each showing its name, contract_type, purpose, and source. A top-level navigation link SHALL join the prompt management area with the existing rubric management area in the same web app.

#### Scenario: List all prompts
- **WHEN** a user opens the prompts listing
- **THEN** every prompt stored in the database is shown with its name, contract_type, purpose, and source

### Requirement: Prompt Detail View
The system SHALL show a single prompt's name, contract_type, purpose, source, description, and its full `content` body.

#### Scenario: View a prompt
- **WHEN** a user opens a prompt
- **THEN** its name, contract_type, purpose, source, description, and full content are displayed

### Requirement: Create Prompt
The system SHALL allow creating a new generation prompt with a name, contract_type, purpose, content, and optional description. The name SHALL be unique among prompts.

#### Scenario: Create a new prompt
- **WHEN** a user submits a new prompt with name `draft_lease`, contract_type `lease`, purpose `drafting`, and a content body
- **THEN** a prompt row is stored with `source = local`
- **AND** the user is redirected to the new prompt's detail view

#### Scenario: Reject duplicate prompt name
- **WHEN** a user submits a prompt whose name already belongs to an existing prompt
- **THEN** the submission is rejected with a clear validation error
- **AND** no prompt row is created

### Requirement: Edit Prompt
The system SHALL allow editing a prompt's name, contract_type, purpose, content, and description.

#### Scenario: Edit a prompt's content
- **WHEN** a user changes a prompt's content body and saves
- **THEN** the prompt row is updated with the new content
- **AND** the user is redirected back to the prompt's detail view

### Requirement: Delete Prompt
The system SHALL allow deleting a generation prompt.

#### Scenario: Delete a prompt
- **WHEN** a user deletes a prompt
- **THEN** the prompt row is removed from the database
- **AND** the user is redirected to the prompts listing

### Requirement: Prompt JSON API
The system SHALL expose the list of prompts, a single prompt, and prompt create/update/delete operations as JSON under `/api/prompts`, so the same data is scriptable. Write operations SHALL delegate to the same manage layer the HTML flows use.

#### Scenario: Fetch prompts as JSON
- **WHEN** a client requests the prompts JSON endpoint
- **THEN** a JSON array of prompts is returned, each with name, contract_type, purpose, and source

#### Scenario: Create a prompt via JSON
- **WHEN** a client POSTs a valid prompt payload to `/api/prompts`
- **THEN** the prompt is created and returned as JSON with status 201

#### Scenario: Manage-layer errors map to HTTP statuses
- **WHEN** a prompt write fails validation, conflict, or not-found
- **THEN** the response uses the same HTTP status mapping as the rubric API (400, 409, 404 respectively)

### Requirement: Prompt Type in the Management UI
The prompt management UI (list, form, detail) SHALL surface `prompt_type` as an editable field. The list SHALL display each prompt's `prompt_type`; the form SHALL accept a `prompt_type` input on create and edit; the detail view SHALL show it. The JSON API models (`PromptCreate`, `PromptUpdate`) and endpoints SHALL carry `prompt_type` through create/update/read.

#### Scenario: Create a prompt with a type from the UI
- **WHEN** the user creates a prompt via the form, filling `prompt_type = experimental`
- **THEN** the stored prompt has `prompt_type = experimental`
- **AND** the detail page shows `experimental`

#### Scenario: Edit a prompt's type
- **WHEN** the user edits a prompt and changes `prompt_type` from `experimental` to `improved`
- **THEN** the stored `prompt_type` becomes `improved`

#### Scenario: The list shows prompt types
- **WHEN** the user views `/prompts`
- **THEN** each row shows its `prompt_type` (blank when unset)

#### Scenario: The API carries prompt_type
- **WHEN** `POST /api/prompts` or `PATCH /api/prompts/{name}` is called with a `prompt_type`
- **THEN** the field is persisted and returned by `GET /api/prompts/{name}`
