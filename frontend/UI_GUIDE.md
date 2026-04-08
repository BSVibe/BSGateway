# BSGateway Dashboard - UI Guidelines

## Overview

The BSGateway Dashboard is a multi-tenant LLM routing control panel built with React 18, TypeScript, TailwindCSS, and Recharts. It allows tenants to:
- View real-time routing decisions and usage metrics
- Manage routing rules with priority-based matching
- Register and configure LLM models with custom API endpoints
- Define custom intents for semantic routing
- Test routing logic before deployment
- Audit all admin operations

---

## Global Layout

### Sidebar Navigation
- **Location**: Fixed left column, 224px (w-56)
- **Background**: Dark gray (bg-gray-900)
- **Header**: Shows tenant name (or "LLM Routing Dashboard" if not logged in)
- **Nav Items**: 7 main sections (Dashboard, Routing, Models, Routing Test, Analytics, API Keys, Audit Log).
  Intents are no longer a top-level page — they are managed inline as part of each routing rule.
- **Active State**: Highlighted with bg-gray-800 + blue right border (border-r-2 border-blue-500)
- **Footer**: Logout button

### Main Content Area
- **Layout**: flex-1 with padding (p-6)
- **Background**: Light gray (bg-gray-50)
- **Scrollable**: overflow-auto for long content

---

## Page Guidelines

### 1. LoginPage

**Purpose**: Exchange API key for JWT token (single tenant session)

**Flow**:
1. User enters API key (bsg_...)
2. Calls `POST /api/v1/auth/token`
3. Stores JWT + tenant metadata in sessionStorage
4. Redirects to dashboard

**Form Fields**:
- **API Key** (password field with show/hide toggle)
  - Type: Text input with WebkitTextSecurity masking
  - Placeholder: "bsg_..."
  - Shows Show/Hide button on right
  - Can be copied even when hidden (CSS masking, not type="password")
  - Hint: "Your API key identifies the tenant automatically."

**Error States**:
- 401: "Invalid or expired API key"
- 403: "Tenant is deactivated"
- Network error: Shows in banner above button

**UX Notes**:
- Auto-focus on API key input
- Show loading spinner while submitting ("Signing in...")
- Disable submit button while loading

---

### 2. DashboardPage

**Purpose**: Overview of current routing status, quick stats, and recent activity

**Sections**:
- **Header**: "Dashboard" title
- **Quick Stats** (cards):
  - Active Rules (count)
  - Registered Models (count)
  - Daily Requests (from usage API)
  - Routing Success Rate (%)

- **Recent Activity** (list or table):
  - Last 10 routing decisions
  - Columns: Timestamp, Model, Rule Matched, Status (Success/Failed)

- **Usage Trend** (chart):
  - Recharts line chart showing requests over last 7 days
  - X-axis: Date
  - Y-axis: Request count

**No Form**: Read-only dashboard

**Refresh**:
- Data refreshes on page load
- Manual refresh button in header

---

### 3. RoutesPage (Routing Rules)

**Purpose**: Notion Mail-style routing — describe what kind of requests should
go to which model in plain natural language. The page hides priority/condition
internals; each card is a single Intent + Rule pair joined by a
`classified_intent == intentName` condition (see `frontend/src/api/routes.ts`).

**Layout**:
- Page width capped at `max-w-4xl`
- Header: "Routing Rules" + "Add Rule" button
- Subtitle: "Describe what kind of requests should go to which model."
- Stacked card list, default fallback rendered last

**RouteCard (non-default)**:
- Active dot toggle on the left (`bg-tertiary` glow when active, click to enable/disable)
- Center: natural-language description text + target model selector +
  priority badge (P0, P1, …) + expandable examples count
- Hover-reveal delete button (two-stage confirmation via `useDeleteConfirm`)
- Expanding the card reveals example phrases (intent training data) with
  add/remove inline editing

**RouteCard (default fallback)**:
- Compact horizontal layout with `flag` icon
- Inline model selector
- "Used when no other rule matches." subtitle
- Same hover-reveal delete

**Create Modal** (only 2 required inputs):
- **어떤 요청을 라우팅할까요?** — natural-language description textarea (required)
- **어떤 모델로 보낼까요?** — dropdown of registered TenantModels (required)
- **예시 문장 추가 (선택)** — collapsible section for optional intent examples
  that improve embedding-based intent matching

**Behind the scenes** (`routesApi.create`):
1. Slugifies the description into an `intent.name`
2. Creates an `Intent` with `description = input` and `examples = input`
3. Creates a `Rule` with `target_model = input`, auto-assigned next priority,
   and a single condition `{condition_type: "intent", field: "classified_intent",
   operator: "eq", value: intent.name}`
4. On rule failure, the intent is rolled back

**Data Sorting**: Cards are sorted by priority ascending; default rules pinned
to the bottom.

**Legacy `/intents` route**: redirects to `/rules`. The standalone IntentsPage
component still exists in source for safety but is not wired into the router.

---

### 4. ModelsPage

**Purpose**: Register LLM models with custom endpoints and credentials

**Create Model Form**:
- **Visibility**: Toggle with "Register Model" button

**Form Fields**:
- **Alias** (text, required)
  - Placeholder: "gpt-4o"
  - Internal name within tenant (used in rules)
  - Hint: "Tenant 내부에서 사용할 이름"

- **Model Name** (text, required)
  - Placeholder: "openai/gpt-4o"
  - LiteLLM model ID in format: provider/model
  - Examples: "openai/gpt-4o", "anthropic/claude-3-opus", "ollama/mistral"
  - Hint: "LiteLLM 모델 ID (provider/model)"

- **API Base** (URL, optional)
  - Placeholder: "http://localhost:11434"
  - Custom endpoint (e.g., for self-hosted models)
  - Only fill if model is NOT using default provider endpoint
  - Hint: "Custom API base URL for non-standard endpoints"

- **API Key** (password, optional)
  - Placeholder: "sk-..."
  - Credentials for the model provider
  - Encrypted at rest (AES-256-GCM)
  - Only shown as dots (masked)

**Models Table**:
- **Columns**:
  - Model Name (alias) - font-medium
  - Provider badge (blue) - extracted from litellm_model (e.g., "openai")
  - Status badge (red) if is_active=false
  - Full litellm_model in mono font
  - API base (if set) in small gray text

- **Actions**:
  - Delete button (two-stage confirmation like Rules)
  - Errors show in ErrorBanner above table

**UX Notes**:
- Alias is what users put in rule's "Target Model"
- Model Name is what goes to LiteLLM API
- Provider is auto-derived from Model Name (e.g., "openai/gpt-4o" → "openai" badge)
- API Key is masked and encrypted

---

### 5. IntentsPage (deprecated)

**Status**: Removed from the dashboard navigation. Intents are now created
implicitly when adding a routing rule on the RoutesPage — see "RoutesPage" above.

**Backend behavior is unchanged**: the rules engine still classifies requests
via embedding similarity (`bsgateway/rules/intent.py`). The dashboard simply
exposes intents as natural-language fields on each route card instead of as a
separate management surface.

The `/intents` route now redirects to `/rules`. The original `IntentsPage.tsx`
component remains in the source tree but is not imported anywhere.

---

### 6. RoutingTestPage

**Purpose**: Manually test routing logic before deploying to production

**Test Form**:
- **Layout**: Single column form

**Form Fields**:
- **Model** (select, required)
  - Dropdown of all registered models
  - Placeholder: "Select model"

- **Request Messages** (dynamic list, at least 1 required)
  - Role (select): "user", "assistant", "system"
  - Content (textarea): The message text
  - Add/Remove buttons

- **Test Button**: "Test Routing"
  - Shows loading spinner while request is processed

**Response**:
- **Box**: bg-white rounded shadow p-6
- **Fields**:
  - **Selected Model**: Which model was chosen (after rule evaluation)
  - **Matched Rule**: Which rule (if any) triggered this selection
  - **Rule Conditions**: Display matched conditions for transparency
  - **Alternative Models**: Show other available models (in case user wants to override)
  - **Latency**: How long evaluation took

**Error Handling**:
- If route selection fails: Show error message
- If model not found: Show helpful error

**UX Notes**:
- This is a debugging tool for admins
- Shows the full decision path (not just final result)
- Useful for testing new rules before activation

---

### 7. UsagePage

**Purpose**: View routing usage statistics and trends

**Filters** (top of page):
- **Period**: Dropdown (day, week, month)
- **Date Range**: Optional from/to date pickers
- "Apply Filters" button

**Summary Stats** (cards):
- **Total Requests**: Number of routing calls
- **Total Tokens**: Sum of input + output tokens
- **Success Rate**: % of successful routes

**Charts** (side by side):
- **By Model** (pie chart):
  - Each model → slice showing % of traffic
  - Legend with request count

- **By Rule** (bar chart):
  - Each rule → bar showing request count
  - X-axis: Rule name
  - Y-axis: Request count

**Daily Breakdown** (line chart):
- X-axis: Date (last 7/30 days)
- Y-axis: Request count
- Hover shows exact date + count

**Table** (below charts, optional):
- Columns: Date, Model, Rule, Requests, Tokens, Success Rate
- Sortable
- Pagination: 50 rows per page

**Data Source**:
- `GET /api/v1/tenants/{tenant_id}/usage?period=week&from=...&to=...`
- Refreshes on page load and filter change

---

### 8. AuditPage

**Purpose**: View audit log of all admin operations (create/delete rules, models, etc.)

**Filters** (top):
- **Action**: Dropdown (all, "rule.created", "model.deleted", "tenant.deactivated", etc.)
- **Resource Type**: Dropdown (all, "rule", "model", "tenant", etc.)
- **Date Range**: From/to date pickers
- "Filter" button

**Audit Log Table**:
- **Columns**:
  - **Timestamp**: ISO format, sortable
  - **Actor**: Admin user (API key prefix or "superadmin")
  - **Action**: Operation type (rule.created, model.deleted, etc.)
  - **Resource**: Type + ID (e.g., "Rule: my-premium-rule")
  - **Status**: Success / Failure
  - **Details**: JSON details or summary text (click to expand)

- **Row Styling**:
  - Failure rows: Light red background
  - Success rows: Normal

- **Pagination**: 50 rows per page
- **Sort**: By timestamp descending (newest first)

**Data Source**:
- `GET /api/v1/tenants/{tenant_id}/audit?limit=50&offset=0&action=...&resource_type=...`

---

## Common UI Components

### LoadingSpinner
- **Usage**: Show while fetching data
- **Style**: Centered, gray spinnericon
- **Text**: "Loading..." (optional)

### ErrorBanner
- **Usage**: Show API errors, validation errors
- **Style**: Red background, white text, rounded corners
- **Actions**: Dismiss button, optional "Retry" button
- **Position**: Top of content area or above table

### DataTable
- **Reusable**: Generic table component
- **Features**: Sorting, pagination, customizable columns
- **Styling**: Striped rows, hover state, responsive

### Form Fields
- **Text Input**: border rounded-lg px-3 py-2 text-sm
- **Textarea**: min-height 100px
- **Select**: Custom styled dropdown (not native)
- **Checkbox**: flex items-center gap-2
- **Password**: Masked with show/hide toggle (LoginPage)

### Buttons
- **Primary** (Create, Register): bg-blue-600 hover:bg-blue-700
- **Success** (Confirm, Submit): bg-green-600 hover:bg-green-700
- **Danger** (Delete, Confirm delete): bg-red-600 hover:bg-red-700
- **Secondary** (Cancel, Dismiss): bg-gray-300 hover:bg-gray-400
- **Disabled State**: opacity-50

### Badges
- **Info**: bg-blue-100 text-blue-800
- **Warning**: bg-yellow-100 text-yellow-800
- **Error**: bg-red-100 text-red-800
- **Neutral**: bg-gray-200 text-gray-700

---

## Color Palette

```
Primary: blue-600 (#2563eb)
Success: green-600 (#16a34a)
Warning: yellow-600 (#ca8a04)
Danger: red-600 (#dc2626)
Dark: gray-900 (#111827)
Light: gray-50 (#f9fafb)
Border: gray-200 (#e5e7eb)
Text: gray-900 (#111827)
Muted: gray-500 (#6b7280)
```

---

## Responsive Design

- **Breakpoints**: Tailwind defaults (sm, md, lg, xl, 2xl)
- **Mobile**: Stack sidebar + content vertically (sidebar hidden by default, hamburger menu)
- **Tablet**: 2-column grid for some tables
- **Desktop**: Full layout as designed

---

## Data Flow

```
User Login
  ↓
POST /api/v1/auth/token (API key)
  ↓
Store JWT + tenant metadata
  ↓
Authenticated API Calls
  ├── GET /api/v1/tenants/{id}/rules
  ├── GET /api/v1/tenants/{id}/models
  ├── GET /api/v1/tenants/{id}/intents
  ├── GET /api/v1/tenants/{id}/usage
  ├── GET /api/v1/tenants/{id}/audit
  └── POST /api/v1/tenants/{id}/rules/test
```

All API calls include: `Authorization: Bearer {jwt_token}`

---

## Error Handling

- **401 Unauthorized**: Redirect to login
- **403 Forbidden**: Show error banner ("Access denied")
- **404 Not Found**: Show error banner ("Resource not found")
- **422 Validation Error**: Show field-level errors inline
- **500+ Server Error**: Show error banner with "Retry" option

---

## Accessibility

- **Keyboard Navigation**: Tab through all interactive elements
- **Labels**: All form inputs have associated labels
- **ARIA**: Include aria-labels for icon-only buttons
- **Contrast**: All text meets WCAG AA standards
- **Focus States**: Visible focus ring on buttons/inputs

---

## Performance Notes

- **Lazy Load**: Pages are code-split by React Router
- **Caching**: useApi hook caches data until manual refetch
- **Pagination**: Tables show 50 rows per page to avoid huge DOM
- **Charts**: Recharts is lightweight and renders efficiently
- **API Debouncing**: Filter/search inputs debounce API calls (500ms)
