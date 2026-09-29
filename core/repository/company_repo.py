import uuid
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import joinedload, Session
from zoneinfo import ZoneInfo
from datetime import datetime

from shared.database.postgres.database_config import get_db
from core.product_hooks import (
    run_company_config_updated_hooks,
    run_company_created_hooks,
)
from core.tables import company_tables
from shared.database.postgres import serialization
from shared.utils.error import error
from shared.utils.constants import constants




class CompanyRepository:
    def __init__(self, db: Session):
        self.db = db
    def get_company_uuid_from_id(self, company_id: int) -> str:
        return str(
            self.db.query(company_tables.Company)
            .filter(company_tables.Company.id == company_id)
            .first()
            .uuid
        )
    def get_company_by_id(self, company_id: int) -> company_tables.Company:
        return self.db.query(company_tables.Company).filter(company_tables.Company.id == company_id).first()

    def get_company_id_from_uuid(self, company_id):
        company = self.db.query(company_tables.Company).filter(company_tables.Company.uuid == company_id).first()
        return company.id if company else None

    def company_exists(self, company_name) -> bool:
        if not company_name:
            return False
        return (
            self.db.query(company_tables.Company.id)
            .filter(company_tables.Company.company_name == company_name)
            .first()
            is not None
        )

    def company_uuid_exists(self, company_uuid) -> bool:
        return (
            self.db.query(company_tables.Company.id)
            .filter(company_tables.Company.uuid == company_uuid)
            .first()
            is not None
        )

    def get_companies(self, page: int, limit: int):
        total_count = self.db.query(company_tables.Company).count()

        companies = (
            self.db.query(company_tables.Company)
            .limit(limit)
            .offset((page - 1) * limit)
            .all()
        )

        company_ids = [company.id for company in companies]

        image_analyses = (
            self.db.query(company_tables.ImageAnalysis)
            .filter(company_tables.ImageAnalysis.company_id.in_(company_ids))
            .all()
            if company_ids
            else []
        )
        return total_count, companies, image_analyses

    def create_company(self, data):
        try:
            company = company_tables.Company(
                uuid=data.eco_id or str(uuid.uuid4()),
                company_name=data.company_name,
                url=data.url,
                address=data.address,
                company_info=data.company_info,
                industry=data.industry,
                target_group=data.target_group,
                tone_analysis=data.tone_analysis,
                logo_url=data.logo_url,
                favicon_url=data.favicon_url,
                theme_colors=data.theme_colors,
                fonts_typography=data.fonts_typography,
                products=data.products,
                keywords=data.keywords,
                matched_fonts=data.matched_fonts,
                product_categories=data.product_categories,
                tier=data.tier or "FREE",
                agent_category=data.agent_category,
            )

            self.db.add(company)
            self.db.flush()

            self.db.add(
                company_tables.ImageAnalysis(
                    company_id=company.id,
                    composition_and_style=data.composition_and_style,
                    environment_settings=data.environment_settings,
                    image_types_and_animation=data.image_types_and_animation,
                    keywords_for_ai_image_generation=data.keywords_for_ai_image_generation,
                    subjects_and_people=data.subjects_and_people,
                    technology_elements=data.technology_elements,
                    theme_and_atmosphere=data.theme_and_atmosphere,
                    analyzed_images_urls=data.analyzed_images,
                    image_urls=data.image_urls,
                )
            )

            # Products attach their own per-company setup here. Runs inside this
            # transaction against the flushed company, so a hook that raises rolls
            # the company back with it — the same all-or-nothing behaviour as when
            # this seeding was inlined above.
            run_company_created_hooks(self.db, company)

            self.db.commit()
            self.db.refresh(company)

            return company

        except Exception:
            self.db.rollback()
            raise

    def create_company_owner(self, company_id, user_id):
        company_user = company_tables.CompanyUser(
            company_id=company_id,
            user_id=user_id,
            role_id=2,
        )

        self.db.add(company_user)
        self.db.commit()

    def create_default_company_features(self, company_id):
        features = self.db.query(company_tables.Feature).all()

        company_features = [
            company_tables.CompanyFeature(
                company_id=company_id,
                feature_id=feature.id,
                enabled=True,
            )
            for feature in features
        ]

        self.db.add_all(company_features)
        self.db.commit()


    def update_company_feature(self, company_id_int, feature_id, enabled):
        try:
            feature = (
                self.db.query(company_tables.CompanyFeature)
                .filter(
                    company_tables.CompanyFeature.company_id == company_id_int,
                    company_tables.CompanyFeature.feature_id == feature_id,
                )
                .first()
            )

            if feature is None:
                raise error.NotFound("Company feature not found")

            feature.enabled = enabled

            self.db.commit()
            self.db.refresh(feature)

            return serialization.sqlalchemy_to_dict(feature)

        except Exception:
            self.db.rollback()
            raise
            

    def get_company_features(self, company_id_int):
        features = (
            self.db.query(company_tables.CompanyFeature)
            .options(joinedload(company_tables.CompanyFeature.feature))
            .filter(company_tables.CompanyFeature.company_id == company_id_int)
            .all()
        )

        return [
            {
                "id": feature.id,
                "uuid": str(feature.uuid) if feature.uuid else None,
                "feature_id": feature.feature_id,
                "feature_name": feature.feature.name if feature.feature else None,
                "enabled": feature.enabled,
            }
            for feature in features
        ]

    def patch_company_billing(self, company_uuid, update_data):
        try:
            company = (
                self.db.query(company_tables.Company)
                .filter(company_tables.Company.uuid == company_uuid)
                .first()
            )

            if company is None:
                raise error.NotFound(f"Company {company_uuid} not found")

            if "tier" in update_data:
                company.tier = update_data["tier"]

            if "agent_category" in update_data:
                company.agent_category = update_data["agent_category"]

            self.db.commit()
            self.db.refresh(company)

            return company

        except Exception:
            self.db.rollback()
            raise

    def get_all_company_notification_emails(self):
        return (
            self.db.query(
                company_tables.Company.uuid,
                company_tables.Company.company_name,
                company_tables.CompanyConfig.notification_email_recipients,
            )
            .outerjoin(
                company_tables.CompanyConfig,
                company_tables.CompanyConfig.company_id == company_tables.Company.id,
            )
            .order_by(company_tables.Company.id)
            .all()
        )

    def get_company_notification_emails(self, company_ids):
        numeric_company_ids = [
            int(company_id)
            for company_id in company_ids
            if company_id.isdigit()
        ]

        filters = [
            cast(company_tables.Company.uuid, String).in_(company_ids)
        ]

        if numeric_company_ids:
            filters.append(
                company_tables.Company.id.in_(numeric_company_ids)
            )

        return (
            self.db.query(
                company_tables.Company.uuid,
                company_tables.Company.company_name,
                company_tables.CompanyConfig.notification_email_recipients,
            )
            .outerjoin(
                company_tables.CompanyConfig,
                company_tables.CompanyConfig.company_id == company_tables.Company.id,
            )
            .filter(or_(*filters))
            .order_by(company_tables.Company.id)
            .all()
        )

    def get_company_by_uuid(self, company_uuid):
        company = (
            self.db.query(company_tables.Company)
            .filter(company_tables.Company.uuid == company_uuid)
            .first()
        )

        if company is None:
            raise error.NotFound(f"Company {company_uuid} not found")

        return company

    def get_company(self, company_uuid):
        company = self.get_company_by_uuid(company_uuid)

        image_analysis = (
            self.db.query(company_tables.ImageAnalysis)
            .filter(company_tables.ImageAnalysis.company_id == company.id)
            .first()
        )

        return company, image_analysis

    def get_company_from_id(self, company_id: int):
        return (
            self.db.query(company_tables.Company)
            .filter(company_tables.Company.id == company_id)
            .first()
        )

    def get_image_analysis(self, company_id):
        return (
            self.db.query(company_tables.ImageAnalysis)
            .filter(company_tables.ImageAnalysis.company_id == company_id)
            .first()
        )

    def normalize_client_update_keys(self, data: dict) -> dict:
        """
        Map camelCase keys (common from browsers) onto snake_case expected by the ORM.
        Celery JSON or non-Pydantic callers may send camelCase only.
        """
        if not data:
            return data
        out = dict(data)
        for camel, snake in (
            ("imageUrls", "image_urls"),
            ("analyzedImages", "analyzed_images"),
            ("analyzedImagesUrls", "analyzed_images_urls"),
        ):
            if camel in out:
                if snake not in out or out[snake] is None:
                    out[snake] = out[camel]
                del out[camel]
        return out


    def image_analysis_model_kwargs(self, data: dict) -> dict:
        """Map API field names to ImageAnalysis columns."""
        out = {}
        for k, v in data.items():
            if k == "analyzed_images":
                out["analyzed_images_urls"] = v
            else:
                out[k] = v
        return out

    def mutate_company_from_payload(self, company_uuid: str, company_data: dict):
        company_data = self.normalize_client_update_keys(company_data)

        company, _ = self.get_company(company_uuid)

        company_fields, image_fields = self._split_fields(company_data)

        self._apply_updates(company, company_fields)

        self._update_image_analysis(company.id, image_fields)

        return company

    def _split_fields(self, company_data):
        company_fields = {}
        image_fields = {}

        for key, value in company_data.items():
            if key in constants.IMAGE_ANALYSIS_FIELDS:
                image_fields[key] = value
            else:
                company_fields[key] = value

        return company_fields, image_fields


    def _update_image_analysis(self, company_id, fields):
        if not fields:
            return

        image = self.get_image_analysis(company_id)

        mapped = self.image_analysis_model_kwargs(fields)

        if image:
            self._apply_updates(image, mapped)
        else:
            mapped["company_id"] = company_id
            self.db.add(company_tables.ImageAnalysis(**mapped))

    def _apply_updates(self, model, values):
        for key, value in values.items():
            if hasattr(model, key):
                setattr(model, key, value)

    def update_company(self, company_uuid, payload):
        try:
            company = self.mutate_company_from_payload(
                company_uuid,
                payload,
            )

            self.db.commit()
            self.db.refresh(company)

            return company

        except Exception:
            self.db.rollback()
            raise
    
    def delete_company(self, company_uuid):
        try:
            company = self.get_company_by_uuid(company_uuid)

            # TODO:
            # delete company posts
            # delete company themes
            # delete company usage
            # delete other dependent records

            self.db.delete(company)

            self.db.commit()

        except Exception:
            self.db.rollback()
            raise


    def create_company_config(self, company_id_int, data):
        try:
            existing = (
                self.db.query(company_tables.CompanyConfig)
                .filter(
                    company_tables.CompanyConfig.company_id == company_id_int
                )
                .first()
            )

            if existing:
                raise error.BadRequest(
                    "A company configuration already exists for this company. "
                    "Please update the existing configuration instead."
                )

            config = company_tables.CompanyConfig(
                company_id=company_id_int,
                supported_languages=data.supported_languages,
                default_language=data.default_language,
                location_mode=data.location_mode,
                company_address=data.company_address,
                business_hours=data.business_hours,
                exception_hours=data.exception_hours,
                notification_email_recipients=data.notification_email_recipients,
                bookings_enabled=data.bookings_enabled,
                caller_data_collection=data.caller_data_collection,
                callback_settings=data.callback_settings,
                phone_no=data.phone_no,
                phone_summary=data.phone_summary,
                email_summary=data.email_summary,
                customer_sms_enabled=data.customer_sms_enabled,
            )

            self.db.add(config)
            self.db.commit()
            self.db.refresh(config)

            return config

        except Exception:
            self.db.rollback()
            raise

            
    def get_company_config_by_company(self, company_uuid):
        company_id = self.get_company_id_from_uuid(company_uuid)

        return (
            self.db.query(company_tables.CompanyConfig)
            .filter(company_tables.CompanyConfig.company_id == company_id)
            .order_by(company_tables.CompanyConfig.created_at.desc())
            .first()
        )
    
    def get_company_config(self, config_uuid):
        return (
            self.db.query(company_tables.CompanyConfig)
            .filter(company_tables.CompanyConfig.uuid == config_uuid)
            .first()
        )

    def delete_company_config(self, config_uuid):
        try:
            config = (
                self.db.query(company_tables.CompanyConfig)
                .filter(company_tables.CompanyConfig.uuid == config_uuid)
                .first()
            )

            if config is None:
                raise error.NotFound("Company configuration not found")

            self.db.delete(config)
            self.db.commit()

        except Exception:
            self.db.rollback()
            raise
    
    def update_company_config(self, config_uuid, update_data):
        try:
            config = (
                self.db.query(company_tables.CompanyConfig)
                .filter(company_tables.CompanyConfig.uuid == config_uuid)
                .first()
            )

            if config is None:
                raise error.NotFound("Company configuration not found")

            for key, value in update_data.items():
                if hasattr(config, key):
                    setattr(config, key, value)

            self.db.commit()
            self.db.refresh(config)

            return config

        except Exception:
            self.db.rollback()
            raise

    def update_notification_config(self, data):
        try:
            company_id = self.get_company_id_from_uuid(data.company_id)

            config = self._get_or_create_company_config(company_id)

            self._apply_notification_updates(
                config,
                data,
            )

            # Products that duplicate these fields mirror them onto their own rows.
            # Runs before commit so core and product stay in one transaction.
            run_company_config_updated_hooks(self.db, company_id, data)

            self.db.commit()
            self.db.refresh(config)

            return config

        except Exception:
            self.db.rollback()
            raise
    
    def _get_or_create_company_config(self, company_id):
        config = (
            self.db.query(company_tables.CompanyConfig)
            .filter(company_tables.CompanyConfig.company_id == company_id)
            .first()
        )

        if config:
            return config

        config = company_tables.CompanyConfig(
            company_id=company_id,
            supported_languages=["sv-SE"],
            default_language="sv-SE",
            location_mode="on_site",
            bookings_enabled=True,
        )

        self.db.add(config)
        self.db.flush()

        return config

    def parse_scheduled_email_time_string(self, value: str):
        """
        Parse API time string into a timezone-aware datetime.time for PostgreSQL TIME WITH TIME ZONE.
        Accepts e.g. 16:27:02+05:30 or 1970-01-01T16:27:02+05:30.
        """
        s = value.strip()
        if not s:
            raise ValueError("scheduled_email_time must be a non-empty string")
        if "T" not in s:
            dt = datetime.fromisoformat(f"1970-01-01T{s}")
        else:
            dt = datetime.fromisoformat(s)
        t = dt.timetz()
        if t.tzinfo is None:
            raise ValueError(
                "scheduled_email_time must include a timezone offset (e.g. 16:27:02+05:30 or 16:27:02Z)"
            )
        return t


    def validate_iana_timezone(self, name: str) -> str:
        """Return stripped name if it is a valid IANA zone (e.g. Asia/Kolkata)."""
        n = name.strip()
        if not n:
            raise ValueError("scheduled_timezone must be a non-empty string")
        ZoneInfo(n)
        return n

    def _apply_notification_updates(
            self,
            config,
            data,
        ):
        if data.phone_no is not None:
            config.phone_no = data.phone_no

        if data.phone_summary is not None:
            config.phone_summary = data.phone_summary

        if data.email_summary is not None:
            config.email_summary = data.email_summary

        if data.daily_summary is not None:
            config.daily_summary = data.daily_summary

        if data.customer_sms_enabled is not None:
            config.customer_sms_enabled = data.customer_sms_enabled

        if data.sms_email is not None:
            config.sms_email = data.sms_email

        if data.email_recipients is not None:
            config.notification_email_recipients = [
                str(email).strip()
                for email in data.email_recipients
                if email and str(email).strip()
            ]

        elif getattr(data, "email_receipient", None) is not None:
            config.notification_email_recipients = [data.email_receipient]

        if "scheduled_email_time" in data.model_fields_set:
            config.scheduled_email_time = (
                None
                if data.scheduled_email_time is None
                else self.parse_scheduled_email_time_string(
                    data.scheduled_email_time
                )
            )

        if "scheduled_timezone" in data.model_fields_set:
            config.scheduled_timezone = (
                None
                if data.scheduled_timezone is None
                else self.validate_iana_timezone(
                    data.scheduled_timezone
                )
            )

        if (
            config.scheduled_email_time
            and not (config.scheduled_timezone or "").strip()
        ):
            raise error.BadRequest(
                "scheduled_timezone is required when scheduled_email_time is set."
            )

            
    def get_notification_config(self, company_uuid):
        company_id = self.get_company_id_from_uuid(company_uuid)

        config = (
            self.db.query(company_tables.CompanyConfig)
            .filter(company_tables.CompanyConfig.company_id == company_id)
            .first()
        )

        if config is None:
            raise error.NotFound(
                "Notification configuration not found"
            )

        return config


    def update_channel_config(self, company_id, update_data):
        config = self.get_channel_config(company_id)

        for key, value in update_data.items():
            if hasattr(config, key):
                setattr(config, key, value)

        self.db.commit()
        self.db.refresh(config)

        return config
        

    def validate_company_id(self, company_id: int) -> None:
        """Raise 404 if company does not exist."""
        company = self.db.query(company_tables.Company).filter(company_tables.Company.id == company_id).first()
        if not company:
            raise error.NotFound(message="Company not found")

    





