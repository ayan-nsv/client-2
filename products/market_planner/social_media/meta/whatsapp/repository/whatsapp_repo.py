from sqlalchemy.orm import Session
from datetime import datetime, UTC

from products.market_planner.social_media.meta.whatsapp.tables import whatsapp_tables


class WhatsAppAccountRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_company_phone(self, company_id: int):
        return self.db.query(whatsapp_tables.WhatsAppAccount).filter(whatsapp_tables.WhatsAppAccount.company_id == company_id).first()
    
    def get_all_whatsapp_accounts(self):
        return self.db.query(whatsapp_tables.WhatsAppAccount).all()

    def create_whatsapp_account(self, company_id, phone_number):
        try:
            acc = self.get_company_phone(company_id)
            if not acc:
                return None
            if acc:
                acc.phone_number = phone_number
                acc.updated_at = datetime.now(UTC)
                self.db.commit()
                self.db.refresh(acc)
                return acc
            acc = whatsapp_tables.WhatsAppAccount(company_id=company_id, phone_number=phone_number)
            self.db.add(acc)
            self.db.commit()
            self.db.refresh(acc)
            return acc
        except Exception as e:
            self.db.rollback()
            return None
   
    def get_whatsapp_account(self, company_id: int):
        return self.db.query(whatsapp_tables.WhatsAppAccount).filter(whatsapp_tables.WhatsAppAccount.company_id == company_id).first()

    def delete_whatsapp_account(self, company_id: int):
        try:
            acc = self.get_whatsapp_account(company_id)
            if not acc:
                return False
            self.db.delete(acc)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            return False

class WhatsAppThemeDeliveryRepository:
    def __init__(self, db: Session):
        self.db = db
    
    def create_theme_delivery(self, company_id, theme_id, recipient_phone, message_token, twilio_sid, month, option1_title, option1_desc, option2_title, option2_desc):
        try:
            delivery = whatsapp_tables.WhatsAppThemeDelivery(
                company_id=company_id,
                theme_id=theme_id,
                recipient_phone=recipient_phone,
                message_token=message_token,
                twilio_message_sid=twilio_sid,
                status="pending",
                month=month,
                option1_title=option1_title,
                option1_desc=option1_desc,
                option2_title=option2_title,
                option2_desc=option2_desc,
            )
            self.db.add(delivery)
            self.db.commit()
            self.db.refresh(delivery)
            return delivery
        except Exception as e:
            self.db.rollback()
            return None
   
    def supersede_pending_themes(self, company_id, except_message_token):
        try:
            self.db.query(whatsapp_tables.WhatsAppThemeDelivery).filter(
                    whatsapp_tables.WhatsAppThemeDelivery.company_id == company_id,
                    whatsapp_tables.WhatsAppThemeDelivery.status == "pending",
                    whatsapp_tables.WhatsAppThemeDelivery.message_token != except_message_token,
                ).update({"status": "superseded", "updated_at": datetime.now(UTC)}, synchronize_session="fetch")
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            return False

    def get_theme_delivery_by_token(self, message_token):
        return self.db.query(whatsapp_tables.WhatsAppThemeDelivery).filter(
            whatsapp_tables.WhatsAppThemeDelivery.message_token == message_token
        ).first()

    def update_theme_delivery_answered(self, delivery_id, selected_option, selected_option_title, selected_option_desc):
        try:
            d = self.db.query(whatsapp_tables.WhatsAppThemeDelivery).filter(whatsapp_tables.WhatsAppThemeDelivery.id == delivery_id).first()
            if not d:
                return
            d.status = "answered"
            d.selected_option = selected_option
            d.selected_option_title = selected_option_title
            d.selected_option_desc = selected_option_desc
            d.updated_at = datetime.now(UTC)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            return False

    def list_theme_deliveries(self, company_id, status):
        q = self.db.query(whatsapp_tables.WhatsAppThemeDelivery).filter(whatsapp_tables.WhatsAppThemeDelivery.company_id == company_id)
        if status:
            q = q.filter(whatsapp_tables.WhatsAppThemeDelivery.status == status)
        rows = q.order_by(whatsapp_tables.WhatsAppThemeDelivery.created_at.desc()).all()
        return [
            {
                "theme_id": d.message_token or str(d.id),
                "status": d.status,
                "selected_option": d.selected_option,
                "selected_option_title": d.selected_option_title,
                "month": d.month,
                "sent_at": d.created_at.isoformat() if d.created_at else None,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                "recipient": d.recipient_phone,
                "company_id": company_id,
            }
            for d in rows
        ]

    def get_pending_theme_deliveries(self, company_id, cutoff):
        return self.db.query(whatsapp_tables.WhatsAppThemeDelivery).filter(
                whatsapp_tables.WhatsAppThemeDelivery.company_id == company_id,
                whatsapp_tables.WhatsAppThemeDelivery.status == "pending",
                whatsapp_tables.WhatsAppThemeDelivery.created_at != None,
                whatsapp_tables.WhatsAppThemeDelivery.created_at < cutoff,
            ).all()

    def get_theme_delivery_by_theme_id(self, theme_db_id):
        return self.db.query(whatsapp_tables.WhatsAppThemeDelivery).filter(whatsapp_tables.WhatsAppThemeDelivery.theme_id == theme_db_id)


class WhatsAppPostDeliveryRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_post_delivery(self, company_id, message_token, recipient_phone, twilio_sid, post_id):
        try:
            delivery = whatsapp_tables.WhatsAppPostDelivery(
                company_id=company_id,
                post_id=post_id,
                recipient_phone=recipient_phone,
                message_token=message_token,
                twilio_message_sid=twilio_sid,
                status="sent",
            )
            self.db.add(delivery)
            self.db.commit()
            self.db.refresh(delivery)
            return delivery
        except Exception as e:
            self.db.rollback()
            return None

    def get_post_delivery_by_token(self, message_token):
        return self.db.query(whatsapp_tables.WhatsAppPostDelivery).filter(
            whatsapp_tables.WhatsAppPostDelivery.message_token == message_token
        ).first()
    
    def update_post_delivery_status(self, delivery_id, status):
        try:
            d = self.db.query(whatsapp_tables.WhatsAppPostDelivery).filter(whatsapp_tables.WhatsAppPostDelivery.id == delivery_id).first()
            if not d:
                return
            d.status = status
            d.updated_at = datetime.now(UTC)
            if status == "approved":
                d.approved_at = datetime.now(UTC)
                d.rejected_at = None
            else:
                d.rejected_at = datetime.now(UTC)
                d.approved_at = None
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            return False

    def list_post_deliveries(self, company_id, status):
        q = self.db.query(whatsapp_tables.WhatsAppPostDelivery).filter(whatsapp_tables.WhatsAppPostDelivery.company_id == company_id)
        if status:
            q = q.filter(whatsapp_tables.WhatsAppPostDelivery.status == status)
        rows = q.order_by(whatsapp_tables.WhatsAppPostDelivery.created_at.desc()).all()
        return [
            {
                "post_id": d.message_token or str(d.id),
                "status": d.status,
                "approved_at": d.approved_at.isoformat() if d.approved_at else None,
                "rejected_at": d.rejected_at.isoformat() if d.rejected_at else None,
                "sent_at": d.created_at.isoformat() if d.created_at else None,
                "processed_at": d.updated_at.isoformat() if d.updated_at else None,
                "recipient": d.recipient_phone,
                "company_id": company_id,
                "twilio_sid": d.twilio_message_sid,
            }
            for d in rows
        ]

    def get_pending_post_deliveries(self, company_id, cutoff):
        return self.db.query(whatsapp_tables.WhatsAppPostDelivery).filter(
                whatsapp_tables.WhatsAppPostDelivery.company_id == company_id,
                whatsapp_tables.WhatsAppPostDelivery.status == "sent",
                whatsapp_tables.WhatsAppPostDelivery.created_at != None,
                whatsapp_tables.WhatsAppPostDelivery.created_at < cutoff,
            ).all()