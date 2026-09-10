# Google Drive Tools Reference

MCP tools for Google Drive file management, search, content retrieval, and permission control. All tools require `user_google_email` (string, required).

## Contents
- Search & Browse: search_drive_files, list_drive_items, list_recent_files
- Content & Download: get_drive_file_content, get_drive_file_download_url
- Create & Modify: create_drive_file, create_drive_folder, copy_drive_file, update_drive_file
- Permissions & Sharing: set_drive_file_permissions, manage_drive_access, get_drive_file_permissions, get_drive_shareable_link, check_drive_file_public_access
- Import: import_to_google_doc
- Tips

---

## Search & Browse

### search_drive_files
Search for files and folders across My Drive and shared drives.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| query | string | yes | | Google Drive search query (see operators below). **WARNING:** Owner-based queries (`'user@example.com' in owners`) do NOT work in Shared Drives - see Shared Drives Limitations below |
| page_size | integer | no | 10 | Max results to return |
| page_token | any | no | | Pagination token |
| drive_id | string | no | | Shared drive ID to scope search |
| include_items_from_all_drives | boolean | no | true | Include shared drive items when no drive_id set |
| corpora | string | no | | `user`, `domain`, `drive`, or `allDrives`. Defaults to `drive` when drive_id is set. Prefer `user` or `drive` over `allDrives` |
| file_type | string | no | | Friendly name (`folder`, `document`/`doc`, `spreadsheet`/`sheet`, `presentation`/`slides`, `form`, `drawing`, `pdf`, `shortcut`, `script`, `site`, `jam`/`jamboard`) or raw MIME type |
| detailed | boolean | no | true | Include size, creation/modification times, last editor, and link. **Verbosity only** -- it does not change what the tool can see |
| order_by | string | no | | Sort order (see Sort Order below) |
| include_trashed | boolean | no | false | Include files in the trash. A `trashed` clause (`=` or `!=`) written into `query` always wins over this flag |
| include_sharing | boolean | no | **false** | Fetch each file's ACLs and annotate publicly shared files with `Anyone with link: <role>`. A **privilege** switch, deliberately separate from `detailed` and opt-in |

**On `include_sharing`.** It is off by default because this is a `core`-tier tool and sharing state is the question `get_drive_file_permissions` and `check_drive_file_public_access` are gated to the `complete` tier for -- fetching ACLs here by default let the lowest tier answer it. Prefer those two tools when sharing state is what you actually want: they report it fully, whereas this only flags the "anyone with link" case. **An absent annotation is not evidence a file is unshared** -- it means either no `anyone` permission or that ACLs were never fetched, and Drive omits the permissions field entirely for Shared Drive items regardless.

### list_drive_items
List files and folders in a specific folder.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| folder_id | string | no | root | Folder ID. Use shared drive ID for its root |
| page_size | integer | no | 100 | Max items to return |
| page_token | any | no | | Pagination token |
| drive_id | string | no | | Shared drive ID to scope listing |
| include_items_from_all_drives | boolean | no | true | Include shared drive items when no drive_id set |
| corpora | string | no | | `user`, `drive`, `allDrives` |
| file_type | string | no | | Same friendly names as search_drive_files |
| detailed | boolean | no | true | Include size, modified time, and link |
| order_by | string | no | | Sort order (see Sort Order below) |

### list_recent_files
List the user's most recent files, newest first, with no query needed. Use this whenever recency *is* the question -- "what have I been working on?", "what did I open recently?", "show me my latest docs". For anything with search terms use `search_drive_files`; for the contents of one folder use `list_drive_items`.

This is also the correct tool for recent activity in **Shared Drives**, where owner-based queries return nothing (see Shared Drives Limitations below).

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| order_by | string | no | recency | Recency signal to sort on, always descending (see Recency Sort Names below) |
| page_size | integer | no | 10 | Max results to return |
| page_token | any | no | | Pagination token. **Pass the same `order_by` on every page** -- the token does not carry it, and omitting it silently reverts to `recency` mid-sequence |
| file_type | string | no | | Same friendly names as search_drive_files |
| drive_id | string | no | | Shared drive ID to scope listing |
| include_items_from_all_drives | boolean | no | true | Include shared drive items when no drive_id set |
| corpora | string | no | | `user`, `domain`, `drive`, or `allDrives`. Defaults to `drive` when drive_id is set |
| detailed | boolean | no | true | Include size, creation/modification times, last editor, shared drive ID, and link |
| include_trashed | boolean | no | false | Include files in the trash |

Detailed output includes `Drive ID:` for files that live in a shared drive (same as `list_drive_items`, and unlike `search_drive_files`) -- useful when results span several drives and you need to tell them apart.

**Recency Sort Names** (`order_by`) -- case-, underscore- and hyphen-insensitive, so `lastModifiedByMe`, `last_modified_by_me` and `last-modified-by-me` are the same value:

| Name | Drive key applied | Meaning |
|------|-------------------|---------|
| `recency` (default) | `recency desc` | Drive's blended most-recent-activity signal |
| `lastModified` | `modifiedTime desc` | Last time **anyone** modified the file |
| `lastModifiedByMe` | `modifiedByMeTime desc` | Last time **this user** modified the file |
| `lastViewedByMe` | `viewedByMeTime desc` | Last time this user opened the file |
| `created` | `createdTime desc` | Newest files first. Google advises against `createdTime` on large collections -- prefer `lastModified` there |
| `sharedWithMe` | `sharedWithMeTime desc` | Most recently shared with this user |

The first three **values** are the three sort orders Google's own first-party Drive MCP server accepts, so those carry over. Only the values match: that server takes camelCase `orderBy` / `pageSize` / `pageToken` and silently falls back to `recency` on an unsupported value, while this tool takes snake_case and raises. It is not a drop-in caller swap.

Every sort is **descending** -- ascending time order is never what "recent" means. A redundant trailing ` desc` is accepted and stripped (`'modifiedTime desc'` works), but an explicit ` asc` raises rather than silently returning the opposite order. An unrecognized name also raises rather than falling back to a default; the error lists every accepted name. For ascending order, or arbitrary multi-key sorts (e.g. `folder,modifiedTime desc,name`), use `search_drive_files` or `list_drive_items`, whose `order_by` is passed to Drive verbatim.

**The sort key is not shown in the output.** Results carry `Created:` and `Modified:` times only, so for `recency`, `lastModifiedByMe`, `lastViewedByMe` and `sharedWithMe` the visible timestamps will appear out of order relative to the sort — the column you can see is not the one the list was sorted on. The header reports the sort *requested*, which is the honest claim: Drive documents that it ignores the requested order for accounts with very large file counts, and does not define where rows missing the sort key land.

`sharedWithMe` and `lastViewedByMe` add a matching query clause so results are restricted to files that actually carry the key. **`lastModifiedByMe` cannot** -- Drive has no `modifiedByMeTime` search term -- so in a large drive where you edited only a few files, that sort ranks many rows that have no such timestamp at all. Prefer `lastViewedByMe` or `recency` unless you specifically need "files I edited".

⚠️ **Do not combine `order_by='sharedWithMe'` with `drive_id`.** Shared drive files are reached through drive membership and are not in your "Shared with me" collection, so the two conditions intersect to nothing and you get `No recent files found` — which looks identical to an empty drive. For recent activity within one shared drive use the default `recency`, or `lastModified`, with `drive_id`.

**No permission data.** This tool never requests file ACLs, so no "Anyone with link" annotation appears — and unlike `search_drive_files` it has no `include_sharing` flag to turn them on. That is deliberate: an absent annotation would be indistinguishable from "not shared", and Drive omits the field entirely for Shared Drive items. Use `get_drive_file_permissions` or `check_drive_file_public_access` when sharing state is the question.

---

## Content & Download

### get_drive_file_content
Retrieve file content as text.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| file_id | string | yes | | Drive file ID |

Content handling:
- Google Docs/Sheets/Slides: exported as text/CSV
- Office files (.docx/.xlsx/.pptx): parsed to extract readable text
- Other files: downloaded, UTF-8 decoded if possible

### get_drive_file_download_url
Download a file to local disk (stdio mode) or get a temporary URL (HTTP mode, valid 1 hour).

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| file_id | string | yes | | Drive file ID |
| export_format | string | no | | `pdf`, `docx`, `xlsx`, `csv`, `pptx` |

Default export formats for Google native files:
- Docs: PDF (or `docx`)
- Sheets: XLSX (or `pdf`, `csv`)
- Slides: PDF (or `pptx`)

---

## Create & Modify

### create_drive_file
Create a new file in Drive without converting it to a native Google format. For
Office-to-Google conversion, use `import_to_google_doc`,
`import_to_google_sheets`, or `import_to_google_slides`.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| file_name | string | yes | | Name for the new file |
| content | string | no | | File content |
| folder_id | string | no | root | Parent folder ID |
| mime_type | string | no | text/plain | MIME type of the file |
| fileUrl | string | no | | Fetch content from this URL (file://, http://, https://) |
| base64_content | string | no | | Standard base64-encoded binary content |
| content_mime_type | string | with base64_content | | Source MIME type; Google-native MIME types are rejected |
| base64_sha256 | string | no | | Optional SHA-256 integrity check for decoded binary content |

The import tools also accept `base64_content` and optional `base64_sha256` for
binary Office/OpenDocument sources. ZIP-based formats are checked for required
members and CRC/decompression errors before Drive is called.

### create_drive_folder
Create a new folder.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| folder_name | string | yes | | Name for the new folder |
| parent_folder_id | string | no | root | Parent folder ID |

### copy_drive_file
Copy an existing file.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| file_id | string | yes | | ID of the file to copy |
| new_name | string | no | | New name (defaults to "Copy of [original]") |
| parent_folder_id | string | no | root | Destination folder ID |

### update_drive_file
Update file metadata and properties.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| file_id | string | yes | | File ID to update |
| name | string | no | | New file name |
| description | string | no | | New description |
| mime_type | string | no | | New MIME type (may require content upload) |
| add_parents | string | no | | Comma-separated folder IDs to add as parents |
| remove_parents | string | no | | Comma-separated folder IDs to remove from parents |
| starred | boolean | no | | Star or unstar |
| trashed | boolean | no | | Move to or restore from trash |
| writers_can_share | boolean | no | | Whether editors can share |
| copy_requires_writer_permission | boolean | no | | Prevent viewers from copying/printing/downloading |
| properties | object | no | | Custom key-value properties |

Move a file between folders by setting both `add_parents` and `remove_parents`.

---

## Permissions & Sharing

### set_drive_file_permissions
High-level tool for link sharing and file-level sharing settings.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| file_id | string | yes | | File or folder ID |
| link_sharing | string | no | | `off`, `reader`, `commenter`, or `writer` |
| writers_can_share | boolean | no | | Whether editors can change permissions |
| copy_requires_writer_permission | boolean | no | | Prevent viewers from copying/printing/downloading |

### manage_drive_access
Consolidated tool for all permission operations: grant, batch grant, update, revoke, transfer ownership.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| file_id | string | yes | | File or folder ID |
| action | string | yes | | `grant`, `grant_batch`, `update`, `revoke`, or `transfer_owner` |
| share_with | string | no | | Email, domain name, or omit for "anyone". Used by `grant` |
| role | string | no | reader (for grant) | `reader`, `commenter`, or `writer` |
| share_type | string | no | user | `user`, `group`, `domain`, or `anyone` |
| permission_id | string | no | | Required for `update` and `revoke` |
| recipients | array | no | | For `grant_batch`: array of `{email, role?, share_type?, expiration_time?}` objects. Use `domain` field instead of `email` for domain shares |
| send_notification | boolean | no | true | Send notification emails |
| email_message | string | no | | Custom notification message |
| expiration_time | string | no | | RFC 3339 format, e.g. `2026-12-31T00:00:00Z` |
| allow_file_discovery | boolean | no | | For domain/anyone shares, whether file appears in search |
| new_owner_email | string | no | | Required for `transfer_owner` |
| move_to_new_owners_root | boolean | no | false | Move file to new owner's My Drive root |

### get_drive_file_permissions
Get detailed file metadata including all sharing permissions.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| file_id | string | yes | | File ID |

### get_drive_shareable_link
Get the shareable link and current sharing status.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| file_id | string | yes | | File or folder ID |

### check_drive_file_public_access
Search for a file by name and check if it has public link sharing enabled.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| file_name | string | yes | | File name to search for |

---

## Drive Search Query Operators

The `query` parameter of `search_drive_files` uses Google Drive query syntax (e.g. `name contains`, `mimeType =`, `'id' in parents`, `modifiedTime >`, `trashed =`, `sharedWithMe`). Combine with `and`/`or`/`not`.

**Trash:** `search_drive_files`, `list_drive_items` and `list_recent_files` all exclude trashed files by default. To see trashed files, pass `include_trashed=true` to `search_drive_files` or `list_recent_files`, or write an explicit `trashed = true` clause into `search_drive_files`'s `query` — an explicit clause always wins over the flag.

---

## Sort Order

The `order_by` parameter controls result ordering for `search_drive_files` and `list_drive_items`. These raw Drive keys are passed through verbatim by those two tools. **`list_recent_files` does not accept them** -- it takes a small set of friendly names instead (see Recency Sort Names above).

**Valid sort keys:**
- `createdTime` - When the file was created
- `folder` - Folders first, then files
- `modifiedByMeTime` - Last time the requesting user modified the file
- `modifiedTime` - Last time anyone modified the file
- `name` - File name (case-sensitive)
- `name_natural` - File name (natural sort order)
- `quotaBytesUsed` - Storage space used
- `recency` - Recently used by the user
- `sharedWithMeTime` - When the file was shared with the user
- `starred` - Starred files first
- `viewedByMeTime` - Last time the user viewed the file

**Modifiers:**
- Add `desc` after a key to sort in descending order (default is ascending)
- Combine multiple keys with commas: `folder,modifiedTime desc,name`

**Examples:**
- `modifiedTime desc` - Most recently modified files first
- `folder,name` - Folders first, then by name within each group
- `starred desc,modifiedTime desc` - Starred files first, then by modified time

**Limitation:** For users with approximately one million files, the requested sort order may be ignored.

---

## Shared Drives Limitations

**IMPORTANT:** Files in Shared Drives have different ownership models than My Drive files:

**Ownership:**
- Files in Shared Drives are owned by the **shared drive itself**, not individual users
- The `owners` and `ownerNames` fields are **NOT populated** for Shared Drive files
- The `ownedByMe` field is always false

**Query Impact:**
- Owner-based queries **DO NOT WORK** in Shared Drives:
  - ❌ `'user@example.com' in owners` - Will not return expected results
  - ❌ `ownedByMe=true` - Will not find files in Shared Drives
- To find recent files in Shared Drives, do **not** query by owner. Instead:
  - ✅ `list_recent_files` (with `drive_id` to scope it) -- the direct route, no query needed
  - ✅ `search_drive_files` with `modifiedTime > '2026-01-01T00:00:00'` and `order_by='modifiedTime desc'` -- when you need a **time window**, which `list_recent_files` does not support
  - ✅ `search_drive_files` by name, type, or content with `order_by='modifiedTime desc'` -- when you need **search terms** as well as recency

**Other field limitations in Shared Drives:**
- `permissions` - Not returned directly; use `get_drive_file_permissions` instead
- `shared` - All items are automatically shared (always true)
- `folderColorRgb` - Individual folder coloring not supported
- `writersCanShare` - Cannot restrict sharing by role

**Finding a user's recent activity:**
Use `list_recent_files` -- it needs no query and no owner clause, so it is unaffected by this limitation:
- `list_recent_files` with `order_by='lastModifiedByMe'` for files **this user** last edited
- `list_recent_files` with `order_by='recency'` (the default) for general recent activity
- Add `drive_id` to scope it to one shared drive

Only fall back to a hand-built `search_drive_files` query when you need recency *combined with* search terms — e.g. `name contains 'budget'` plus `order_by='modifiedTime desc'`.

---

## File Types

The `file_type` parameter on search/list tools accepts friendly names directly (e.g. `folder`, `document`, `spreadsheet`, `pdf`, `csv`) -- no need to use full MIME type strings.

---

## Import

### import_to_google_doc
Imports a file (Markdown, DOCX, TXT, HTML, RTF, ODT) into Google Docs format with automatic conversion.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| user_google_email | string | yes | | |
| file_name | string | yes | | Name for the new Google Doc |
| content | any | no | | Text content for MD, TXT, HTML |
| file_path | any | no | | Local file path for DOCX, ODT, etc. Supports `file://` URLs |
| file_url | any | no | | Remote URL to fetch (http/https) |
| source_format | any | no | (auto-detect) | `md`, `markdown`, `docx`, `txt`, `html`, `rtf`, `odt` |
| folder_id | string | no | root | Parent folder ID |

---

## Tips

**Shared drives**: Set `drive_id` to scope operations. When `drive_id` is set, `corpora` defaults to `drive`. For folder operations in shared drives, use a folder ID within that drive (or the drive ID itself for root).

**Pagination**: `search_drive_files`, `list_drive_items` and `list_recent_files` all return a `nextPageToken` line when more results exist. Pass it back as `page_token` to get the next page. Results are incomplete without paginating.

**Choosing a browse tool**: recency only -> `list_recent_files`; search terms -> `search_drive_files`; one folder's contents -> `list_drive_items`.

**No metadata caching in this server**: every Drive listing, search, and metadata tool queries the API on each call, so there is nothing here to refresh or invalidate after a write. Note this says nothing about Drive's own index, which is eventually consistent — a just-created file may not appear in the very next list. If a write succeeded but the file is missing from the next listing, wait and re-list rather than treating the write as failed or retrying it.

The one exception is file *bytes*, not metadata: in HTTP mode `get_drive_file_download_url` saves the downloaded file to server-side attachment storage and returns a URL valid for 1 hour. That stored copy is a snapshot -- if the file changes within the hour, re-run the tool to get a fresh URL rather than reusing the old one.

**Moving files**: Use `update_drive_file` with `add_parents` (destination) and `remove_parents` (source) set together.

**Permission workflow**: Use `get_drive_file_permissions` to inspect current permissions (and get permission IDs), then `manage_drive_access` with `action: "update"` or `action: "revoke"` using those IDs.

**Batch sharing**: Use `manage_drive_access` with `action: "grant_batch"` and a `recipients` list to share with multiple people in one call.

**Link sharing shortcut**: Use `set_drive_file_permissions` with `link_sharing` to quickly toggle "anyone with the link" access without dealing with permission IDs.
