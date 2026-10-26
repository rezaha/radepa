"""Compatibility aliases: old commands now use direct metadata lookup, never SMTP."""
from app.handlers.breach import breach_command as verifyemail_command
from app.handlers.breach import receive_email as receive_verify_email
