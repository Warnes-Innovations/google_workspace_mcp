# Google Sheets Tools Reference

MCP tools for reading, writing, formatting, and managing Google Sheets. All tools require `user_google_email` (string, required). The `spreadsheet_id` parameter accepts a spreadsheet ID or a full Google Sheets URL.

## Contents
- Search & Info: list_spreadsheets, get_spreadsheet_info
- Read & Write: read_sheet_values, modify_sheet_values
- Create: create_spreadsheet, create_sheet, move_sheet_rows
- Structured tables: list_sheet_tables, append_table_rows
- Sheet dimensions: resize_sheet_dimensions
- Formatting: format_sheet_range, manage_conditional_formatting
- Comments: list_spreadsheet_comments, manage_spreadsheet_comment
- Tips

---

## Search & Info

### list_spreadsheets
List spreadsheets the user has access to (via Drive).

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| max_results | integer | no | 25 | |

### get_spreadsheet_info
Get spreadsheet metadata: title, locale, and list of sheets.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |

---

## Read & Write

### read_sheet_values
Read values from a range in a spreadsheet.

Open-ended or oversized A1 ranges are clamped to at most **1000 rows** before
the Sheets API request (same budget as the default `A1:Z1000`). When clamped,
the response includes a note with the rewritten range so you can request the
next window (e.g. `A1001:A2000`). Quoted whole-sheet references such as
`'My Sheet'` are clamped as well. Bare identifiers are left unchanged because
Google Sheets can resolve them as named ranges.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| range_name | string | no | A1:Z1000 | A1 notation, e.g. `Sheet1!A1:D10`. Caps at 1000 rows |
| include_hyperlinks | boolean | no | false | Fetch hyperlink metadata (slower) |
| include_notes | boolean | no | false | Fetch cell notes (slower) |

### modify_sheet_values
Write, update, or clear values in a range.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| range_name | string | yes | | A1 notation |
| values | array or string | conditional | | 2D array of values. Required unless `clear_values=true`. Accepts a JSON string or a list |
| value_input_option | string | no | USER_ENTERED | `RAW` or `USER_ENTERED` |
| clear_values | boolean | no | false | Clear the range instead of writing |

---

## Create

### create_spreadsheet
Create a new Google Spreadsheet.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| title | string | yes | | Spreadsheet title |
| sheet_names | array of strings | no | | Sheet names to create. Defaults to one sheet with the default name |

### create_sheet
Add a new sheet (tab) to an existing spreadsheet.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| sheet_name | string | yes | | |

### move_sheet_rows
Move rows from one sheet to another within the same spreadsheet. Preserves formulas, data types, and formatting.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| source_sheet | string | yes | | Name of the sheet to move rows from |
| start_row | integer | yes | | First row to move (1-based, inclusive) |
| end_row | integer | yes | | Last row to move (1-based, inclusive) |
| destination_sheet | string | yes | | Name of the sheet to move rows to |

---

## Structured Tables

Google Sheets "tables" are a named, typed range with its own schema -- not the same
thing as a plain block of cells. Appending through the table API extends the table
range, so banding, filters and column types follow the new rows; writing the same
cells with `modify_sheet_values` does not.

### list_sheet_tables
List every structured table in a spreadsheet with its ID, name, range, and columns.
Run this first -- `append_table_rows` needs a `table_id`, and there is no other way
to discover one.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |

### append_table_rows
Append rows to the end of a structured table's body, extending the table range.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| table_id | string | yes | | From `list_sheet_tables` |
| values | array or JSON string | yes | | 2D array; each inner list is one row |

---

## Sheet Dimensions

### resize_sheet_dimensions
Sheet-level dimension properties in one call: resize, auto-resize, freeze,
hide/unhide, and insert/delete rows and columns. Every parameter below is
optional except the first two -- pass only the operations you want.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| sheet_name | string | no | first sheet | |
| column_sizes | dict or JSON string | no | | Column letter to pixel width, e.g. `{"A": 200}` |
| row_sizes | dict or JSON string | no | | 1-based row number to pixel height, e.g. `{"1": 40}` |
| auto_resize_columns | array or JSON string | no | | Column letters to fit to content, e.g. `["A", "B"]` |
| auto_resize_rows | array or JSON string | no | | 1-based row numbers to fit to content |
| frozen_row_count | integer | no | | Rows frozen from the top; `0` unfreezes |
| frozen_column_count | integer | no | | Columns frozen from the left; `0` unfreezes |
| hide_columns | array or JSON string | no | | Column letters |
| unhide_columns | array or JSON string | no | | Column letters |
| hide_rows | array or JSON string | no | | 1-based row numbers |
| unhide_rows | array or JSON string | no | | 1-based row numbers |
| insert_rows | integer | no | | How many rows to insert |
| insert_rows_at | integer | no | end of sheet | 1-based row to insert before |
| insert_columns | integer | no | | How many columns to insert |
| insert_columns_at | string | no | end of sheet | Column letter to insert before |
| delete_rows | array or JSON string | no | | 1-based row numbers; best for non-contiguous |
| delete_row_range | string | no | | Contiguous `"start:end"`, 1-based inclusive, e.g. `"5:10"` -- cheaper than `delete_rows` for large runs |
| delete_columns | array or JSON string | no | | Column letters |

---

## Formatting

### format_sheet_range
Apply visual formatting to a range: colors, number formats, text wrapping, alignment, and text styling.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| range_name | string | yes | | A1 notation (with optional sheet name) |
| background_color | string | no | | Hex `#RRGGBB` |
| text_color | string | no | | Hex `#RRGGBB` |
| number_format_type | string | no | | `NUMBER`, `CURRENCY`, `DATE`, `PERCENT`, etc. |
| number_format_pattern | string | no | | Custom pattern for the number format |
| wrap_strategy | string | no | | `WRAP`, `CLIP`, or `OVERFLOW_CELL` |
| horizontal_alignment | string | no | | `LEFT`, `CENTER`, or `RIGHT` |
| vertical_alignment | string | no | | `TOP`, `MIDDLE`, or `BOTTOM` |
| bold | boolean | no | | |
| italic | boolean | no | | |
| font_size | integer | no | | Size in points |

### manage_conditional_formatting
Add, update, or delete conditional formatting rules.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| action | string | yes | | `add`, `update`, or `delete` |
| range_name | string | for add | | A1 notation. Optional for update (preserves existing ranges if omitted) |
| condition_type | string | for add | | e.g. `NUMBER_GREATER`, `TEXT_CONTAINS`, `DATE_BEFORE`, `CUSTOM_FORMULA` |
| condition_values | array or string | conditional | | Values for the condition. Depends on `condition_type` |
| background_color | string | no | | Hex `#RRGGBB` applied when condition matches |
| text_color | string | no | | Hex `#RRGGBB` applied when condition matches |
| rule_index | integer | for update/delete | | 0-based index of the rule |
| gradient_points | array or string | no | | List of gradient point dicts for color-scale rules. Overrides boolean rule parameters |
| sheet_name | string | no | first sheet | Sheet name for locating the rule (used by update/delete) |

---

## Comments

### list_spreadsheet_comments
List all comments on a spreadsheet.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |

### manage_spreadsheet_comment
Create, reply to, or resolve a comment.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| spreadsheet_id | string | yes | | |
| action | string | yes | | `create`, `reply`, or `resolve` |
| comment_content | string | for create/reply | | Comment text |
| comment_id | string | for reply/resolve | | Target comment ID |

---

## Tips

**Range notation**: Use A1 notation throughout. Include the sheet name for multi-sheet spreadsheets (e.g. `Sheet2!A1:C10`). If no sheet name is given, the first sheet is used.

**USER_ENTERED vs RAW**: `USER_ENTERED` (default) parses values as if typed into the Sheets UI -- formulas are evaluated, dates parsed, numbers formatted. `RAW` stores exact strings without interpretation.

**Conditional formatting condition types**: Common values include `NUMBER_GREATER`, `NUMBER_LESS`, `NUMBER_BETWEEN`, `TEXT_CONTAINS`, `TEXT_NOT_CONTAINS`, `DATE_BEFORE`, `DATE_AFTER`, `CUSTOM_FORMULA`, `BLANK`, `NOT_BLANK`.

**Gradient rules**: Provide `gradient_points` as a list of dicts, each with `type` (`MIN`, `MAX`, `NUMBER`, `PERCENT`, `PERCENTILE`), `value` (string, optional for `MIN`/`MAX`), and `color` (hex `#RRGGBB`). When gradient points are set, boolean formatting parameters are ignored.
