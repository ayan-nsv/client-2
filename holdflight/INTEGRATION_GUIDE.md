# Holdflight Integration Guide

This guide explains how to complete the integration of holdflight code into the main market_planner project.

## Current Status

✅ **Completed:**
- Directory structure created in `holdflight/`
- Route file created: `api/holdflight_routes.py`
- Router added to `main.py`
- All placeholder files created

## Next Steps

### 1. Copy Your Holdflight Code

Copy all your holdflight project files into the corresponding files in `holdflight/` directory:

```bash
# Example (adjust paths as needed):
# Copy from your holdflight project to market_planner/holdflight/
```

### 2. Update Route Integration

Once you've copied your code, the integration will work automatically if your `holdflight/src/core/app.py` exports a router. The `api/holdflight_routes.py` file will:

- **Option 1 (Preferred):** If your `app.py` exports a router:
  ```python
  router = APIRouter()
  # ... your routes ...
  ```
  The integration will automatically pick it up.

- **Option 2:** If your `app.py` creates a FastAPI app instance:
  ```python
  app = FastAPI()
  # ... your routes ...
  ```
  The integration will extract routes from the app instance.

- **Option 3:** If you need individual function imports, update `api/holdflight_routes.py`:
  ```python
  from holdflight.src.core.website_analyzer import analyze_website
  from holdflight.src.scraping.scan import scan_website
  # ... create routes using these functions
  ```

### 3. Update Imports in Holdflight Code

After copying, you may need to update imports in your holdflight code:

- **If holdflight uses relative imports:** Update them to absolute imports from `holdflight.src.*`
- **If holdflight has its own config:** Consider merging with main project's config or updating paths
- **If holdflight uses different Firebase/database setup:** Review and align with main project's setup

### 4. Merge Dependencies

Update the main project's `requirements.txt` with any additional dependencies from `holdflight/requirements.txt`:

```bash
# Review holdflight/requirements.txt and add missing packages to main requirements.txt
```

### 5. Test the Integration

1. Start your FastAPI server:
   ```bash
   uvicorn main:app --reload
   ```

2. Check the health endpoint:
   ```bash
   curl http://localhost:8000/api/v1/holdflight/health
   ```

3. Verify all holdflight routes are available:
   ```bash
   # Check API docs at http://localhost:8000/docs
   # Look for "holdflight" tag in the Swagger UI
   ```

## Route Access

Once integrated, your holdflight routes will be available at:
- Base URL: `http://localhost:8000/api/v1/`
- Health check: `http://localhost:8000/api/v1/holdflight/health`
- All other routes from your holdflight app will be accessible under `/api/v1/`

## Troubleshooting

### Import Errors
- Make sure all `__init__.py` files are present in the holdflight directory structure
- Check that Python can find the `holdflight` module (it should be in the project root)

### Route Not Found
- Verify that your `holdflight/src/core/app.py` exports a router or app instance
- Check the logs for any import warnings
- Review `api/holdflight_routes.py` for any error messages

### Dependency Conflicts
- Review both `requirements.txt` files for version conflicts
- Test in a clean virtual environment if needed

## File Structure Reference

```
market_planner/
├── holdflight/              # Holdflight code (merged)
│   └── src/
│       └── core/
│           └── app.py       # Your FastAPI app with routes
├── api/
│   └── holdflight_routes.py # Integration wrapper
└── main.py                  # Main app (includes holdflight router)
```

## Notes

- The main project's code structure remains unchanged
- Holdflight code is isolated in its own directory
- Routes are integrated but code remains separate for easier maintenance
- You can gradually refactor and merge functionality as needed



