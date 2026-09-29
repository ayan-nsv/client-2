"""
Application-wide constants. Use these instead of hardcoding role names/IDs.
"""

# Role IDs (must match `roles` table in the database)
MEMBER_ID = 1
ADMIN_ID = 2
MANAGER_ID = 3

# Role names (for validation and display)
MEMBER = "member"
ADMIN = "admin"
MANAGER = "manager"

# List of valid role names (for validators / APIs)
ROLES = [MEMBER, ADMIN, MANAGER]
