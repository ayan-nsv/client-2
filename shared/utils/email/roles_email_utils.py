from datetime import datetime


from typing import Optional

def get_invitation_email_template(
    inviter_name: str, 
    company_name: str, 
    invite_url: str,
    company_logo: Optional[str] = None
) -> tuple[str, str, str]:
    """
    Generate email content for invitation emails
    
    Args:
        inviter_name: Name of the person sending the invitation
        company_name: Name of the company the user is being invited to
        invite_url: The unique invitation URL
        company_logo: Optional URL for the company logo
        
    Returns:
        tuple: (subject, html_content, text_content)
    """
    current_year = datetime.now().year
    
    subject = f"🎉 You're invited to join {company_name}"
    
    # Logo section: only show if company_logo is provided
    logo_html = ""
    if company_logo:
        logo_html = f'<img src="{company_logo}" alt="{company_name} Logo" class="logo">'
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ text-align: center; padding: 20px 0; }}
            .logo {{ max-width: 150px; margin-bottom: 20px; }}
            .button {{
                display: inline-block;
                padding: 12px 24px;
                background-color: #2563eb;
                color: white !important;
                text-decoration: none;
                border-radius: 6px;
                font-weight: 500;
                margin: 20px 0;
            }}
            .footer {{
                margin-top: 30px;
                padding-top: 20px;
                border-top: 1px solid #e5e7eb;
                font-size: 14px;
                color: #6b7280;
                text-align: center;
            }}
            .code {{
                background: #f3f4f6;
                padding: 2px 6px;
                border-radius: 4px;
                font-family: monospace;
                word-break: break-all;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                {logo_html}
            </div>
            
            <h2>You've been invited to {company_name}!</h2>
            
            <p>Hello,</p>
            
            <p><strong>{inviter_name}</strong> has invited you to join <strong>{company_name}</strong> on Our Platform.</p>
            
            <p>Click the button below to accept the invitation and set up your account:</p>
            
            <p style="text-align: center;">
                <a href="{invite_url}" class="button">Accept Invitation</a>
            </p>
            
            <p>Or copy and paste this link into your browser:</p>
            
            <p class="code">{invite_url}</p>
            
            <p>This invitation link will expire in 7 days.</p>
            
            <p>If you didn't request this invitation, you can safely ignore this email.</p>
            
        </div>
    </body>
    </html>
    """
    
    text_content = f"""
    INVITATION TO JOIN {company_name}
    
    Hello,
    
    {inviter_name} has invited you to join {company_name} on Our Platform.
    
    To accept this invitation, please click the link below:
    
    {invite_url}
    
    If the link doesn't work, copy and paste it into your browser's address bar.
    
    This invitation link will expire in 7 days.
    
    If you didn't request this invitation, you can safely ignore this email.
    """
    
    # Clean up whitespace
    text_content = '\n'.join(line.strip() for line in text_content.split('\n')).strip()
    
    return subject, html_content, text_content
