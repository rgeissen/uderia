from quart import Blueprint, request, jsonify
from pydantic import BaseModel, EmailStr, Field, ValidationError
from trusted_data_agent.auth.email_service import EmailService
import logging
from datetime import datetime

contact_bp = Blueprint('contact', __name__, url_prefix='/api/v1/contact')
logger = logging.getLogger(__name__)

class ContactFormRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    company: str = Field(..., min_length=1, max_length=100)
    message: str = Field(default="", max_length=2000)

@contact_bp.route('/submit', methods=['POST'])
async def submit_contact_form():
    """Handle contact form submissions from promotional website"""
    try:
        # Get JSON data from request
        data = await request.get_json()

        # Validate with Pydantic
        try:
            form_data = ContactFormRequest(**data)
        except ValidationError as e:
            logger.warning(f"Contact form validation error: {e}")
            return jsonify({"success": False, "error": "Invalid form data", "details": e.errors()}), 400

        # Get client IP
        client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)

        # Create HTML email body
        html_body = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                .header {{ background: linear-gradient(135deg, #F15F22 0%, #FF8C50 100%);
                          color: white; padding: 20px; border-radius: 8px 8px 0 0; }}
                .content {{ background: #f9f9f9; padding: 20px; border-radius: 0 0 8px 8px; }}
                .field {{ margin-bottom: 15px; }}
                .label {{ font-weight: bold; color: #F15F22; }}
                .value {{ margin-top: 5px; }}
                .footer {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd;
                          font-size: 12px; color: #666; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2 style="margin: 0;">🎯 New Demo Request</h2>
                    <p style="margin: 5px 0 0 0; opacity: 0.9;">From Uderia Promotional Website</p>
                </div>
                <div class="content">
                    <div class="field">
                        <div class="label">Name:</div>
                        <div class="value">{form_data.name}</div>
                    </div>
                    <div class="field">
                        <div class="label">Email:</div>
                        <div class="value">{form_data.email}</div>
                    </div>
                    <div class="field">
                        <div class="label">Company:</div>
                        <div class="value">{form_data.company}</div>
                    </div>
                    <div class="field">
                        <div class="label">Message:</div>
                        <div class="value">{form_data.message or '(No message provided)'}</div>
                    </div>
                    <div class="footer">
                        <p>Submitted: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
                        <p>IP Address: {client_ip}</p>
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

        # Send email using existing email service
        success = await EmailService.send_email(
            to_email="info@uderia.com",
            subject=f"Demo Request from {form_data.name} ({form_data.company})",
            html_body=html_body
        )

        if not success:
            logger.error(f"Failed to send contact form email for {form_data.email}")
            return jsonify({"success": False, "error": "Failed to send email"}), 500

        logger.info(f"Contact form submitted successfully: {form_data.email} from {form_data.company}")

        return jsonify({"success": True, "message": "Your request has been submitted successfully"}), 200

    except Exception as e:
        logger.error(f"Contact form submission error: {str(e)}", exc_info=True)
        return jsonify({"success": False, "error": "Internal server error"}), 500
