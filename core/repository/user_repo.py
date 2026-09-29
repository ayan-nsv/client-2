
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from core.tables.user_tables import User, Role
from core.tables.company_tables import Company, CompanyUser

from shared.database.postgres import serialization
from shared.utils.constants.roles import ADMIN
from shared.utils.error import error



class UserRepository:
    def __init__(self, db: Session):
        self.db = db
    def create_user(self, data):
        try:
            user_record = self.db.query(User).filter(User.firebase_uid == data.firebase_uid).first()
            if user_record:
                user_record.last_login = datetime.now(timezone.utc)
                self.db.commit()
                self.db.refresh(user_record)
                return serialization.sqlalchemy_to_dict(user_record)
            user = User(
                email=data.email,
                name=data.name,
                is_admin=False,
                is_active=True,
                profile_image=data.profile_image,
                joined_at= datetime.now(),
                last_login= datetime.now(),
                firebase_uid=data.firebase_uid,
                created_at= datetime.now(),
                updated_at= datetime.now()
            )
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)
            return serialization.sqlalchemy_to_dict(user)
        except Exception:
            self.db.rollback()
            raise

    def get_users(self):
        return self.db.query(User).all()

    def get_user(self, user_id):
        return self.db.query(User).filter(User.uuid == user_id).first()

    def get_user_from_id(self, user_id):
        return self.db.query(User).filter(User.id == user_id).first()

    def get_user_by_firebase_id(self, firebase_id):
        return self.db.query(User).filter(User.firebase_uid == firebase_id).first()

    def get_user_role(self, user_id_int, company_id_int):
        return (
            self.db.query(
                CompanyUser.company_id,
                Role.name.label("role_name"),
                User.name.label("user_name"),
            )
            .join(Role, CompanyUser.role_id == Role.id)
            .join(User, CompanyUser.user_id == User.id)
            .filter(
                CompanyUser.user_id == user_id_int,
                CompanyUser.company_id == company_id_int,
            )
            .first()
        )

    def get_role(self, role):
        return self.db.query(Role).filter(Role.name == role).first()

    def get_role_by_id(self, role_id):
        return self.db.query(Role).filter(Role.id == role_id).first()

    def update_user_company_role(self, company_id_int, user_id_int, role_id):
        try:
            company_user = (
                self.db.query(CompanyUser)
                .filter(
                    CompanyUser.company_id == company_id_int,
                    CompanyUser.user_id == user_id_int,
                )
                .first()
            )

            if company_user is None:
                return False

            company_user.role_id = role_id
            self.db.commit()

            return True

        except Exception:
            self.db.rollback()
            return False
        
    def get_user_companies(self, firebase_id):
        return (
                self.db.query(Company.uuid)
                .join(CompanyUser, Company.id == CompanyUser.company_id)
                .join(User, CompanyUser.user_id == User.id)
                .filter(User.firebase_uid == firebase_id)
                .all()
            )
        
    def check_user_company_access(self, user_id_int, company_id_int):
        return (
            self.db.query(CompanyUser)
            .filter(
                CompanyUser.user_id == user_id_int,
                CompanyUser.company_id == company_id_int,
            )
            .first()
        )

    def add_company_users(self, company_ids, user_ids, role_ids):
        try:
            company_users = [
                CompanyUser(
                    company_id=company_id,
                    user_id=user_id,
                    role_id=role_id,
                )
                for company_id, user_id, role_id in zip(company_ids, user_ids, role_ids)
            ]

            self.db.add_all(company_users)
            self.db.commit()

            result = []
            for company_user in company_users:
                self.db.refresh(company_user)
                result.append(serialization.sqlalchemy_to_dict(company_user))

            return result
        except Exception:
            self.db.rollback()
            raise

    def remove_company_users(self, company_users):
        try:
            for company_user in company_users:
                self.db.delete(company_user)

            self.db.commit()

        except Exception:
            self.db.rollback()
            raise
    
    def get_company_users(self, company_id_int):
        return (
                self.db.query(User, Role.name)
                .join(CompanyUser, User.id == CompanyUser.user_id)
                .join(Role, CompanyUser.role_id == Role.id)
                .filter(CompanyUser.company_id == company_id_int)
                .all()
            )
    
    def get_company_user_record(self, company_id_int, user_id_int):
        return self.db.query(CompanyUser).filter(CompanyUser.company_id == company_id_int, CompanyUser.user_id == user_id_int).first()

    def get_companies_of_multiple_users(self, user_ids):
        return (self.db.query(CompanyUser.user_id, Company.uuid, Company.company_name).join(Company, CompanyUser.company_id == Company.id).filter(CompanyUser.user_id.in_(user_ids)).all())

    def update_user(self, user_record, payload):
        try:
            for key, value in payload.items():
                setattr(user_record, key, value)

            self.db.commit()
            self.db.refresh(user_record)

            return serialization.sqlalchemy_to_dict(user_record)

        except Exception:
            self.db.rollback()
            raise

    def get_firebase_user_by_email(self, email):
        return self.db.query(User).filter(User.email == email).first()
    
    def create_pending_user(self, email, firebase_uid):
        try:
            user = User(
                email=email,
                firebase_uid=firebase_uid,
                is_active=False,
                is_admin=False,
                is_fully_approved=True,
                has_created_company=False,
                joined_at=datetime.now(),
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)

            return serialization.sqlalchemy_to_dict(user)

        except Exception:
            self.db.rollback()
            raise

    def get_pending_users(self):
        users = self.db.query(User).filter(User.is_active == False).all()
        return [serialization.sqlalchemy_to_dict(user) for user in users]

    def approve_pending_user(self, pending_user, firebase_uid=None):
        try:
            if firebase_uid:
                pending_user.firebase_uid = firebase_uid

            pending_user.is_active = True

            self.db.commit()
            self.db.refresh(pending_user)

            return pending_user

        except Exception:
            self.db.rollback()
            raise

    
    def delete_user(self, user):
        try:
            self.db.delete(user)
            self.db.commit()

        except Exception:
            self.db.rollback()
            raise

    
    def is_user_admin(self, firebase_uid: str, company_id: int) -> bool:
        user = self.db.query(User).filter(User.firebase_uid == firebase_uid).first()
        if not user:
            return False
        company_user = (
            self.db.query(CompanyUser)
            .filter(
                CompanyUser.user_id == user.id,
                CompanyUser.company_id == company_id,
            )
            .first()
        )
        if not company_user or not company_user.role_id:
            return False
        role = self.db.query(Role).filter(Role.id == company_user.role_id).first()
        return bool(role and role.name and role.name.lower() == ADMIN)


    
   


        