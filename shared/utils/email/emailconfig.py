import asyncio
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from shared.utils.constants import constants 
from shared.utils.error import error

async def send_template_email(
    to_email: str,
    template_id: str,
    dynamic_data: dict,
) -> bool:
    """Send an email using a SendGrid dynamic template.

    ``to_email`` may be a single address or a comma-separated list. ``dynamic_data``
    keys map to the ``{{handlebars}}`` placeholders defined in the template.
    """

    if not constants.SENDGRID_API_KEY or not constants.SENDGRID_FROM_EMAIL or not template_id:
        # logger.error("app_sendgrid_template_config_missing")
        raise error.EmailServiceError("SendGrid configuration is missing")

    recipients = [addr.strip() for addr in str(to_email).split(",") if addr.strip()]
    if not recipients:
        raise error.EmailServiceError("No valid recipient email provided")

    message = Mail(from_email=constants.SENDGRID_FROM_EMAIL, to_emails=recipients)
    message.template_id = template_id
    message.dynamic_template_data = dynamic_data

    def _send():
        sg = SendGridAPIClient(constants.SENDGRID_API_KEY)
        return sg.send(message)

    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send)
        # logger.info("app_sendgrid_template_email_ok template=%s", template_id)
        return True
    except Exception as e:
        # logger.exception(
        #     "app_sendgrid_template_email_failed to=%s template=%s error=%s",
        #     to_email,
        #     template_id,
        #     e,
        # )
        raise error.EmailServiceError(f"Failed to send email via SendGrid: {str(e)}")
