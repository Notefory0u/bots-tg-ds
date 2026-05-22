from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db


class User(UserMixin, db.Model):
    """User model"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    balance = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)
    role = db.Column(db.String(100), default='user', nullable=False)  # 'creator', 'admin', 'moderator', 'tech_admin', 'media', 'user'
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=True, index=True)
    discord_id = db.Column(db.BigInteger, unique=True, nullable=True, index=True)
    discord_sync_code = db.Column(db.String(20), unique=True, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Email verification
    email_verified_at = db.Column(db.DateTime, nullable=True, index=True)
    email_verification_token = db.Column(db.String(255), nullable=True, index=True)
    email_verification_token_expires_at = db.Column(db.DateTime, nullable=True)
    
    # Restrictions and bans
    is_banned = db.Column(db.Boolean, default=False, nullable=False, index=True)
    purchase_blocked = db.Column(db.Boolean, default=False, nullable=False, index=True)
    
    # Tracking
    registration_ip = db.Column(db.String(45), nullable=True)
    last_login_ip = db.Column(db.String(45), nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    
    # Referral system
    referral_code = db.Column(db.String(20), unique=True, nullable=True, index=True)
    referred_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    referral_balance = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)  # Earnings from referrals
    total_referrals = db.Column(db.Integer, default=0, nullable=False)
    total_spent = db.Column(db.Integer, default=0, nullable=False)  # Total amount spent (for loyalty levels) in rubles
    loyalty_level_id = db.Column(db.Integer, db.ForeignKey('loyalty_levels.id'), nullable=True)  # Current loyalty level
    
    # Cost tracking for profit analysis
    cost_price = db.Column(db.Numeric(10, 2), default=0.00, nullable=True) # For bulk estimation if needed
    
    # Custom percent overrides (priority over loyalty level)
    referral_percent_override = db.Column(db.Numeric(5, 2), nullable=True)
    cashback_percent_override = db.Column(db.Numeric(5, 2), nullable=True)
    discount_percent_override = db.Column(db.Numeric(5, 2), nullable=True)
    promocode_discount = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)
    
    # Partner system
    is_partner = db.Column(db.Boolean, default=False, nullable=False, index=True)
    partner_commission = db.Column(db.Numeric(5, 2), nullable=True) # Individual commission %
 
    # Relationships
    orders = db.relationship('Order', backref='user', lazy='dynamic', foreign_keys='Order.user_id')
    transactions = db.relationship('Transaction', backref='user', lazy='dynamic', foreign_keys='Transaction.user_id')
    referred_users = db.relationship('User', backref=db.backref('referrer', remote_side=[id]), lazy='dynamic')
    referral_transactions = db.relationship('ReferralTransaction', backref='user', lazy='dynamic', foreign_keys='ReferralTransaction.user_id')
    
    def set_password(self, password):
        """Set password hash"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check password"""
        return check_password_hash(self.password_hash, password)
    
    def get_roles(self):
        """Get list of active roles for this user"""
        if not self.role:
            return ['user']
        return [r.strip() for r in self.role.split(',') if r.strip()]

    def has_role(self, role_name):
        """Check if user has a specific role"""
        return role_name in self.get_roles()

    def is_admin(self):
        """Check if user is admin or creator"""
        roles = self.get_roles()
        return 'admin' in roles or 'creator' in roles
    
    def is_creator(self):
        """Check if user is creator"""
        return 'creator' in self.get_roles()
    
    def is_moderator(self):
        """Check if user is moderator, admin or creator"""
        roles = self.get_roles()
        return 'moderator' in roles or 'admin' in roles or 'creator' in roles
    
    def is_media(self):
        """Check if user is media"""
        return 'media' in self.get_roles()

    def is_tech_admin(self):
        """Check if user is tech admin, admin or creator"""
        roles = self.get_roles()
        return 'tech_admin' in roles or 'admin' in roles or 'creator' in roles
    
    def can_access_admin(self):
        """Check if user can access admin panel"""
        roles = self.get_roles()
        return any(r in roles for r in ['creator', 'admin', 'moderator', 'tech_admin'])
    
    def can_manage_users(self):
        """Check if user can manage other users"""
        roles = self.get_roles()
        return 'creator' in roles or 'admin' in roles
    
    def can_manage_roles(self):
        """Check if user can change roles (only creator)"""
        return 'creator' in self.get_roles()
    
    def generate_referral_code(self):
        """Generate unique referral code"""
        import secrets
        import string
        
        if not self.referral_code:
            while True:
                code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
                if not User.query.filter_by(referral_code=code).first():
                    self.referral_code = code
                    break
        return self.referral_code
    
    def generate_discord_sync_code(self):
        """Generate 6-digit alphanumeric sync code for Discord"""
        import secrets
        import string
        
        if not self.discord_sync_code:
            while True:
                # 6-digit uppercase alphanumeric code
                code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
                if not User.query.filter_by(discord_sync_code=code).first():
                    self.discord_sync_code = code
                    db.session.commit()
                    break
        return self.discord_sync_code
    
    def get_referral_percent(self):
        """Get referral commission percentage from override or loyalty level"""
        if self.is_partner and self.partner_commission is not None:
            return float(self.partner_commission)
            
        if self.referral_percent_override is not None:
            return float(self.referral_percent_override)
        
        # Fallback to loyalty level
        if self.loyalty_level and self.loyalty_level.is_active:
            return float(self.loyalty_level.referral_percent)
            
        return 0.0

    def get_cashback_percent(self):
        """Get cashback percentage from override or loyalty level"""
        if self.cashback_percent_override is not None:
            return float(self.cashback_percent_override)
        
        # Fallback to loyalty level
        if self.loyalty_level and self.loyalty_level.is_active:
            return float(self.loyalty_level.cashback_percent)
            
        return 0.0

    def get_discount_percent(self):
        """Get discount percentage: (promocode_discount) + (override or loyalty level default)"""
        # Ensure we have floats and handle None
        promocode_disc = float(self.promocode_discount) if self.promocode_discount is not None else 0.0
        
        user_disc = 0.0
        if self.discount_percent_override is not None:
            user_disc = float(self.discount_percent_override)
        elif self.loyalty_level and self.loyalty_level.is_active:
            # Use relationship instead of query.get
            user_disc = float(self.loyalty_level.discount_percent or 0)
        
        total = promocode_disc + user_disc
        return total

    def is_email_verified(self):
        """Check if user's email is verified"""
        return self.email_verified_at is not None
    
    def generate_email_verification_token(self, expires_hours=24):
        """Generate 6-digit email verification code with expiration"""
        import random
        from datetime import timedelta
        
        # Generate 6-digit numeric code
        code = '{:06d}'.format(random.randint(0, 999999))
        
        # Set code and expiration
        self.email_verification_token = code
        self.email_verification_token_expires_at = datetime.utcnow() + timedelta(hours=expires_hours)
        
        return code
    
    def verify_email_token(self, token):
        """Verify 6-digit email verification code"""
        if not self.email_verification_token:
            return False
        
        if self.email_verification_token != str(token).strip():
            return False
        
        expires_at = self.email_verification_token_expires_at
        if not expires_at:
            return False
            
        if hasattr(expires_at, 'tzinfo') and expires_at.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=None)
            
        if datetime.utcnow() > expires_at:
            return False
        
        # Token is valid, verify email
        self.email_verified_at = datetime.utcnow()
        self.email_verification_token = None
        self.email_verification_token_expires_at = None
        
        return True
    
    def update_loyalty_level(self):
        """
        Update user's loyalty level based on total_spent.
        Automatically finds the maximum level where threshold <= total_spent.
        Returns True if level changed, False otherwise.
        """
        from app.models import LoyaltyLevel, Notification
        
        # Get all active levels ordered by threshold descending
        levels = LoyaltyLevel.query.filter_by(is_active=True).order_by(
            LoyaltyLevel.threshold.desc()
        ).all()
        
        # Find the highest level the user qualifies for
        new_level = None
        total_spent_int = int(self.total_spent)
        for level in levels:
            if total_spent_int >= int(level.threshold):
                new_level = level
                break
        
        # If no level found, assign default (Гость level)
        if not new_level:
            new_level = LoyaltyLevel.query.filter_by(name='Гость', is_active=True).first()
        if not new_level and levels:
            new_level = min(levels, key=lambda x: int(x.threshold))
        # Update user's level if changed
        level_changed = False
        if new_level and self.loyalty_level_id != new_level.id:
            self.loyalty_level_id = new_level.id
            level_changed = True
            
            # Send notification about level up
            from app.models import Notification
            notification = Notification(
                user_id=self.id,
                type='loyalty_level_up',
                title='Новый уровень лояльности!',
                message=f'Поздравляем! Вы достигли нового уровня: {new_level.name}. Теперь ваши привилегии еще выше!',
                channel='both',
                is_read=False
            )
            db.session.add(notification)
            
        return level_changed

    def credit_referral_commission(self, order, total_amount):
        """
        Credit referral commission to the referrer if exists.
        Returns the commission amount credited, or 0.
        """
        if not self.referred_by_id:
            return 0
            
        from app.models import ReferralTransaction, Notification, Transaction
        
        referrer = User.query.get(self.referred_by_id)
        if not referrer:
            return 0
            
        referral_percent = referrer.get_referral_percent()
        if referral_percent <= 0:
            return 0
            
        commission = float(total_amount) * (referral_percent / 100)
        
        # Update balances
        referrer.referral_balance = float(referrer.referral_balance or 0) + commission
        referrer.balance = float(referrer.balance or 0) + commission
        
        # Create transaction log for referrer's main history
        ref_deposit = Transaction(
            user_id=referrer.id,
            transaction_type='deposit',
            amount=commission,
            payment_method='referral',
            status='completed',
            completed_at=datetime.utcnow()
        )
        db.session.add(ref_deposit)
        
        # Create referral-specific transaction log
        ref_transaction = ReferralTransaction(
            user_id=referrer.id,
            referred_user_id=self.id,
            order_id=order.id,
            amount=commission,
            percentage=referral_percent
        )
        db.session.add(ref_transaction)
        
        # Create notification for referrer
        notification = Notification(
            user_id=referrer.id,
            type='referral_reward',
            title='Реферальное вознаграждение!',
            message=f'Вы получили {commission:.2f} ₽ за покупку вашего реферала ({self.username}).',
            channel='both',
            is_read=False
        )
        db.session.add(notification)
        
        return commission

    
    def get_price_with_discount(self, base_price):
        """
        Get price with loyalty level or individual discount applied
        """
        discount_percent = self.get_discount_percent()
        if discount_percent > 0:
            discount = float(discount_percent) / 100
            return float(base_price) * (1 - discount)
        return float(base_price)
    
    def get_loyalty_progress(self):
        """
        Calculate progress to the next loyalty level (0-100).
        Returns (current_spent, next_threshold, percentage, next_level_name)
        """
        from app.models import LoyaltyLevel
        
        # Get all active levels ordered by threshold
        levels = LoyaltyLevel.query.filter_by(is_active=True).order_by(LoyaltyLevel.threshold.asc()).all()
        if not levels:
            return 0, 0, 0, None
            
        total_spent = float(self.total_spent)
        next_level = None
        
        for level in levels:
            if float(level.threshold) > total_spent:
                next_level = level
                break
        
        if not next_level:
            # User is at maximum level
            return total_spent, total_spent, 100, "MAX"
            
        # Find current level threshold (previous level)
        current_threshold = 0
        for level in reversed(levels):
            if float(level.threshold) <= total_spent:
                current_threshold = float(level.threshold)
                break
        
        range_size = float(next_level.threshold) - current_threshold
        if range_size <= 0:
            percentage = 100
        else:
            progress = total_spent - current_threshold
            percentage = min(100, max(0, (progress / range_size) * 100))
            
        return total_spent, float(next_level.threshold), int(percentage), next_level.name

    def __repr__(self):
        return f'<User {self.username}>'


class Platform(db.Model):
    """Platform model for products (Steam, Origin, etc.)"""
    __tablename__ = 'platforms'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    icon_class = db.Column(db.String(50), nullable=True) # Lucide icon name or similar
    position = db.Column(db.Integer, default=0, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    products = db.relationship('Product', backref='platform_rel', lazy='dynamic', foreign_keys='Product.platform_id')
    
    def __repr__(self):
        return f'<Platform {self.name}>'


class CheatStatus(db.Model):
    """Status model for cheats (Undetected, Updating, etc.)"""
    __tablename__ = 'cheat_statuses'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    color = db.Column(db.String(20), default='#10b981', nullable=False) # Default green
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<CheatStatus {self.name}>'


class Product(db.Model):
    """Product model"""
    __tablename__ = 'products'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id'), nullable=True, index=True)
    platform_id = db.Column(db.Integer, db.ForeignKey('platforms.id'), nullable=True, index=True)
    description = db.Column(db.Text, nullable=True)
    activation_instructions = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='active', nullable=False)  # 'active' or 'hidden'
    position = db.Column(db.Integer, default=0, nullable=False, index=True)
    is_popular = db.Column(db.Boolean, default=False, nullable=False, index=True)  # For popular products page
    is_on_sale = db.Column(db.Boolean, default=False, nullable=False, index=True)  # For sales page
    discount_percentage = db.Column(db.Numeric(5, 2), default=0, nullable=False)  # Discount percentage
    product_type = db.Column(db.String(50), nullable=True, index=True)  # 'Игры', 'DLC', 'Подписки'
    platform = db.Column(db.String(100), nullable=True, index=True)  # Legacy string field, keeping for compatibility
    views_count = db.Column(db.Integer, default=0, nullable=False)  # For analytics - track views
    product_status = db.Column(db.String(50), default='UnDetect', nullable=False)  # Legacy string status
    cheat_status_id = db.Column(db.Integer, db.ForeignKey('cheat_statuses.id'), nullable=True, index=True)
    software_type = db.Column(db.String(50), default='External', nullable=False, index=True) # 'Internal', 'External', 'Macros'
    criteria = db.Column(db.Text, nullable=True)  # System requirements or other criteria
    trailer_url = db.Column(db.String(500), nullable=True)  # Link to trailer
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships - optimized for faster loading
    items = db.relationship('ProductItem', backref='product', lazy='selectin', order_by='ProductItem.duration_days', cascade='all, delete-orphan')
    images = db.relationship('ProductImage', backref='product', lazy='selectin', order_by='ProductImage.position', cascade='all, delete-orphan')
    promotions = db.relationship('Promotion', back_populates='product', lazy='selectin', cascade='all, delete-orphan')
    cheat_status = db.relationship('CheatStatus', backref='products', lazy='selectin')
    
    def __repr__(self):
        return f'<Product {self.name}>'

    def get_active_promotion(self):
        """Get the currently active promotion for this product (guaranteed scoped to this product)"""
        from datetime import datetime
        now = datetime.utcnow()
        
        # 1. First check preloaded/cached promotions for performance
        if 'promotions' in self.__dict__ or hasattr(self, 'promotions'):
            for promo in self.promotions:
                # Double-check ID to be absolutely sure no cross-product bleeding occurs
                if promo.is_active and int(promo.product_id) == int(self.id):
                    if promo.start_date <= now <= promo.end_date:
                        return promo
        
        # 2. If no active promotion found in cache, do a strict direct query to be 100% safe
        # This acts as a circuit-breaker for any potential relationship/preloading bugs
        from app.models import Promotion
        return Promotion.query.filter_by(
            product_id=self.id, 
            is_active=True
        ).filter(
            Promotion.start_date <= now,
            Promotion.end_date >= now
        ).first()

    def get_discount_info(self):
        """Get info about active discount (from Promotion or legacy Sale)"""
        promo = self.get_active_promotion()
        if promo and promo.promo_type == 'discount':
            return {
                'type': 'promotion',
                'value': float(promo.discount_value),
                'name': promo.name
            }
        
        if self.is_on_sale and self.discount_percentage > 0:
            return {
                'type': 'sale',
                'value': float(self.discount_percentage),
                'name': 'Распродажа'
            }
        
        return None

    @property
    def parsed_description(self):
        """Parse JSON description if it exists"""
        import json
        if not self.description:
            return {}
        try:
            desc = self.description.strip()
            if desc.startswith('{') and desc.endswith('}'):
                return json.loads(desc)
        except:
            pass
        return {}

    @property
    def parsed_features(self):
        """Get features from JSON description"""
        return self.parsed_description.get('features', self.parsed_description.get('functions', ''))

    @property
    def parsed_criteria_items(self):
        """Get list of structured criteria items {"label": "...", "value": "..."}"""
        criteria_raw = self.parsed_description.get('criteria', '')
        if not criteria_raw:
            # Fallback to criteria field if it's a string
            if self.criteria:
                lines = self.criteria.split('\n')
                return [{"label": "ИНФОРМАЦИЯ", "value": line} for line in lines if line.strip()]
            return []
            
        if isinstance(criteria_raw, list):
            items = []
            for item in criteria_raw:
                if isinstance(item, dict):
                    label = item.get('title', item.get('label', 'ИНФО'))
                    value = item.get('value', item.get('content', ''))
                    if value:
                        items.append({"label": label, "value": value})
                elif isinstance(item, str):
                    # For flat lists, take string as value, common labels are stripped or skipped
                    item_clean = item.strip()
                    skip_words = ['Требования', 'Игровой клиент', 'Система', 'Процессор', 'Видеокарта', 'Режим окна']
                    if any(word in item_clean for word in skip_words):
                        continue
                    items.append({"label": "КРИТЕРИЙ", "value": item_clean})
            return items
            
        return []

    @property
    def card_benefit(self):
        """Derive a premium benefit label from the product category"""
        cat = (self.category or "").upper()
        if "SEMI - RAGE" in cat or "SEMI-RAGE" in cat:
            return {"label": "СТИЛЬ ИГРЫ", "value": "Превосходство Semi-Rage"}
        if "RAGE" in cat:
            return {"label": "СТИЛЬ ИГРЫ", "value": "Подходит для Rage игры"}
        if "LEGIT" in cat:
            return {"label": "СТИЛЬ ИГРЫ", "value": "Идеально для Legit игры"}
        if "MACROS" in cat:
            return {"label": "БЕЗОПАСНОСТЬ", "value": "Безопасные макросы"}
        if "EXTERNAL" in cat:
            return {"label": "БЕЗОПАСНОСТЬ", "value": "Высокий уровень защиты"}
        if "INTERNAL" in cat:
            return {"label": "СЛОЖНОСТЬ", "value": "Продвинутый функционал"}
        return {"label": "ПРЕИМУЩЕСТВО", "value": "Элитное качество"}

    @property
    def card_image_url(self):
        """Get the primary image URL for cards, or a fallback"""
        if self.images:
            return self.images[0].image_url
        return None

    @property
    def min_price_per_day(self):
        """Get the minimum price per day across all items"""
        if not self.items:
            return None
        prices = [float(item.price) / item.duration_days for item in self.items if item.duration_days > 0]
        return min(prices) if prices else None

    @property
    def min_price(self):
        """Get the absolute minimum price across all items"""
        if not self.items:
            return None
        prices = [float(item.price) for item in self.items]
        return min(prices) if prices else None
    @property
    def display_status(self):
        """Get the status to display, prioritizing manual cheat_status over legacy product_status"""
        if self.cheat_status:
            return {
                'name': self.cheat_status.name,
                'color': self.cheat_status.color
            }
        
        # Fallback to legacy product_status
        name = self.product_status or 'UnDetect'
        name_lower = name.lower()
        
        if 'undetect' in name_lower:
            color = '#10b981' # Green
        elif 'update' in name_lower or 'maintenance' in name_lower:
            color = '#3b82f6' # Blue
        elif 'detect' in name_lower:
            color = '#ef4444' # Red
        else:
            color = '#71717a' # Gray
            
        return {
            'name': name,
            'color': color
        }


class ProductItem(db.Model):
    """Product item (tariff) model"""
    __tablename__ = 'product_items'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='CASCADE'), nullable=False)
    duration_days = db.Column(db.Integer, nullable=False)  # 1, 7, 30
    duration_label = db.Column(db.String(100), nullable=True) # Text like 'навсегда', 'одноразовый ключ'
    price = db.Column(db.Numeric(10, 2), nullable=False)
    cost_price = db.Column(db.Numeric(10, 2), default=0.00, nullable=False) # Actual cost of keys
    stock = db.Column(db.Integer, default=0, nullable=False)  # Available keys count
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    keys = db.relationship('Key', backref='product_item', lazy='dynamic', cascade='all, delete-orphan')
    order_items = db.relationship('OrderItem', backref='product_item', lazy='dynamic')
    
    @property
    def formatted_duration(self):
        if self.duration_label:
            return self.duration_label
        
        # Pluralize days
        days = self.duration_days
        if days % 10 == 1 and days % 100 != 11:
            suffix = "день"
        elif 2 <= days % 10 <= 4 and (days % 100 < 10 or days % 100 >= 20):
            suffix = "дня"
        else:
            suffix = "дней"
            
        return f"{days} {suffix}"
    
    def __repr__(self):
        return f'<ProductItem {self.duration_days} days>'
    
    def get_price(self, user=None):
        """Get final price for this item after all discounts"""
        base_price = float(self.price)
        
        # 1. Apply Product-level Promotion or Sale
        discount_info = self.product.get_discount_info()
        if discount_info:
            base_price = base_price * (1 - (discount_info['value'] / 100))
            
        # 2. Apply User-level Loyalty Discount (stacks)
        if user and user.is_authenticated:
            # We use the user's discount percent directly to avoid recursive get_price_with_discount calls if they were to use this
            discount_percent = user.get_discount_percent()
            if discount_percent > 0:
                base_price = base_price * (1 - (float(discount_percent) / 100))
                
        return base_price

    def get_discount_data(self, user=None):
        """Get detailed discount data for UI: original_price, final_price, discount_percent, has_discount"""
        base_price = float(self.price)
        final_price = self.get_price(user)
        
        has_discount = final_price < base_price
        discount_percent = 0
        if has_discount and base_price > 0:
            discount_percent = round((1 - final_price / base_price) * 100)
            
        return {
            'original_price': base_price,
            'final_price': final_price,
            'discount_percent': discount_percent,
            'has_discount': has_discount
        }


class ProductImage(db.Model):
    """Product image model"""
    __tablename__ = 'product_images'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='CASCADE'), nullable=False, index=True)

    image_url = db.Column(db.String(500), nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<ProductImage {self.id}>'


class Review(db.Model):
    """User review for a product"""
    __tablename__ = 'reviews'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='CASCADE'), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False) # 1 to 5
    comment = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('User', backref='reviews')
    product = db.relationship('Product', backref='reviews')
    images = db.relationship('ReviewImage', backref='review', lazy='selectin', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Review {self.id} for Product {self.product_id}>'


class ReviewImage(db.Model):
    """Images attached to a user review"""
    __tablename__ = 'review_images'
    
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('reviews.id', ondelete='CASCADE'), nullable=False, index=True)
    image_url = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<ReviewImage {self.id}>'


class Key(db.Model):
    """Key model (encrypted)"""
    __tablename__ = 'keys'
    
    id = db.Column(db.Integer, primary_key=True)
    product_item_id = db.Column(db.Integer, db.ForeignKey('product_items.id', ondelete='CASCADE'), nullable=False, index=True)

    encrypted_key = db.Column(db.Text, nullable=False)  # Encrypted key data
    status = db.Column(db.String(20), default='available', nullable=False)  # 'available', 'sold', 'reserved', 'invalid'
    is_validated = db.Column(db.Boolean, default=False, nullable=False)  # If key was validated
    validation_status = db.Column(db.String(50), nullable=True)  # 'valid', 'invalid', 'pending'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    sold_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True)  # For subscriptions - when key expires
    
    # Relationship
    order_item = db.relationship('OrderItem', backref='key', uselist=False)
    
    @property
    def key_data(self):
        """Decrypt and return the plain text key"""
        if not self.encrypted_key:
            return '-'
        from core.security import decrypt_key
        try:
            return decrypt_key(self.encrypted_key)
        except Exception:
            return "Decryption Error"

    def __repr__(self):
        return f'<Key {self.id}>'


class ReservedKey(db.Model):
    """Reserved key model - for temporary reservation during checkout"""
    __tablename__ = 'reserved_keys'
    
    id = db.Column(db.Integer, primary_key=True)
    key_id = db.Column(db.Integer, db.ForeignKey('keys.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Null for guest
    session_id = db.Column(db.String(255), nullable=True)  # For guest reservations
    reserved_until = db.Column(db.DateTime, nullable=False)  # Reservation expiry time
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    key = db.relationship('Key', backref='reservations')
    user = db.relationship('User', backref='reserved_keys')
    
    def __repr__(self):
        return f'<ReservedKey {self.id}>'


class Order(db.Model):
    """Order model"""
    __tablename__ = 'orders'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), default='pending', nullable=False)  # 'pending', 'paid', 'completed', 'cancelled'
    total_amount = db.Column(db.Numeric(10, 2), nullable=False)
    customer_email = db.Column(db.String(120), nullable=True)  # For guest orders
    customer_telegram_id = db.Column(db.BigInteger, nullable=True)
    payment_method = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    items = db.relationship('OrderItem', backref='order', lazy='dynamic', cascade='all, delete-orphan')
    transactions = db.relationship('Transaction', backref='order', lazy='dynamic')
    
    def __repr__(self):
        return f'<Order {self.order_number}>'


class OrderItem(db.Model):
    """Order item model"""
    __tablename__ = 'order_items'
    
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id', ondelete='CASCADE'), nullable=False, index=True)
    product_item_id = db.Column(db.Integer, db.ForeignKey('product_items.id'), nullable=False, index=True)
    key_id = db.Column(db.Integer, db.ForeignKey('keys.id'), nullable=True)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    price = db.Column(db.Numeric(10, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def get_decrypted_key(self):
        """Get decrypted key for this order item"""
        if not self.key_id:
            return None
        from core.security import decrypt_key
        key_obj = Key.query.get(self.key_id)
        if key_obj:
            try:
                return decrypt_key(key_obj.encrypted_key)
            except Exception:
                return None
        return None
    
    def get_expires_at(self):
        """Calculate expiration date based on purchase date and duration"""
        if not self.created_at:
            return None
        from datetime import timedelta
        if self.product_item:
            return self.created_at + timedelta(days=self.product_item.duration_days)
        return None
    
    def is_expired(self):
        """Check if key is expired"""
        expires_at = self.get_expires_at()
        if not expires_at:
            return False
        return datetime.utcnow() > expires_at
    
    def __repr__(self):
        return f'<OrderItem {self.id}>'


class Transaction(db.Model):
    """Transaction model"""
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True, index=True)
    transaction_type = db.Column(db.String(20), nullable=False)  # 'deposit', 'purchase', 'refund'
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), default='pending', nullable=False)  # 'pending', 'completed', 'failed', 'cancelled'
    external_id = db.Column(db.String(100), nullable=True, index=True)  # External payment ID
    payment_metadata = db.Column(db.Text, nullable=True)  # JSON metadata for payment systems
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    def __repr__(self):
        return f'<Transaction {self.id}>'


class PaymentSystem(db.Model):
    """Payment system model"""
    __tablename__ = 'payment_systems'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    display_name = db.Column(db.String(200), nullable=False)
    configuration = db.Column(db.Text, nullable=True)  # JSON configuration
    enabled = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<PaymentSystem {self.name}>'
        

class Category(db.Model):
    """Category model for products"""
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    products = db.relationship('Product', backref='category_rel', lazy='dynamic', foreign_keys='Product.category_id')
    
    def __repr__(self):
        return f'<Category {self.name}>'


class Game(db.Model):
    """Game model - for game catalog page"""
    __tablename__ = 'games'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    position = db.Column(db.Integer, default=0, nullable=False, index=True)
    genre = db.Column(db.String(100), nullable=True, index=True)  # Added for filtering
    platform = db.Column(db.String(100), nullable=True, index=True) # Added for filtering
    is_legendary = db.Column(db.Boolean, default=False, nullable=False) # Added for UI badge
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    products = db.relationship('Product', backref='game', lazy='dynamic', foreign_keys='Product.game_id')
    
    def __repr__(self):
        return f'<Game {self.name}>'


class ReferralTransaction(db.Model):
    """Referral transaction model"""
    __tablename__ = 'referral_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)  # Referrer
    referred_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)  # Referred user
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True, index=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)  # Commission amount
    percentage = db.Column(db.Numeric(5, 2), nullable=False)  # Commission percentage
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    referred_user = db.relationship('User', foreign_keys=[referred_user_id], backref='referral_bonuses')
    order = db.relationship('Order', backref='referral_transactions')
    
    def __repr__(self):
        return f'<ReferralTransaction {self.id}>'


class PromoCode(db.Model):
    """Promo code model"""
    __tablename__ = 'promo_codes'
    
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    discount_type = db.Column(db.String(20), nullable=False)  # 'percentage' or 'fixed'
    discount_value = db.Column(db.Numeric(10, 2), nullable=False)  # Percentage or fixed amount
    bonus_balance = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)  # Bonus balance to add
    max_uses = db.Column(db.Integer, nullable=True)  # None = unlimited
    uses_count = db.Column(db.Integer, default=0, nullable=False)
    min_order_amount = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    valid_from = db.Column(db.DateTime, nullable=True)
    valid_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    usages = db.relationship('PromoCodeUsage', backref='promo_code', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<PromoCode {self.code}>'
    
    @classmethod
    def deactivate_expired(cls):
        """Deactivate expired promo codes in bulk"""
        now = datetime.utcnow()
        expired = cls.query.filter(
            cls.is_active == True,
            cls.valid_until.isnot(None),
            cls.valid_until < now
        ).all()
        for code in expired:
            code.is_active = False
        if expired:
            db.session.commit()
    
    def is_valid(self, user_id=None, order_amount=0.00):
        """Check if promo code is valid"""
        if not self.is_active:
            return False, "Промокод неактивен"
        
        now = datetime.utcnow()
        if self.valid_from and now < self.valid_from:
            return False, "Промокод еще не действителен"
        
        if self.valid_until and now > self.valid_until:
            # Auto-deactivate
            self.is_active = False
            db.session.commit()
            return False, "Промокод истек"
        
        if self.max_uses and self.uses_count >= self.max_uses:
            return False, "Промокод исчерпан"
        
        if float(order_amount) < float(self.min_order_amount):
            return False, f"Минимальная сумма заказа: {self.min_order_amount} ₽"
        
        if user_id:
            # Check if user already used this code
            usage = PromoCodeUsage.query.filter_by(user_id=user_id, promo_code_id=self.id).first()
            if usage:
                return False, "Вы уже использовали этот промокод"
        
        return True, "OK"


class PromoCodeUsage(db.Model):
    """Promo code usage tracking"""
    __tablename__ = 'promo_code_usages'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    promo_code_id = db.Column(db.Integer, db.ForeignKey('promo_codes.id', ondelete='CASCADE'), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=True)
    discount_amount = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)
    bonus_amount = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<PromoCodeUsage {self.id}>'


class Bonus(db.Model):
    """Bonus model - for cumulative discounts and bonuses"""
    __tablename__ = 'bonuses'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    bonus_type = db.Column(db.String(20), nullable=False)  # 'discount', 'balance', 'cashback'
    value = db.Column(db.Numeric(10, 2), nullable=False)  # Discount percentage, balance amount, or cashback percentage
    min_spent = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)  # Minimum spent to get this bonus
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    position = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<Bonus {self.name}>'


class Cart(db.Model):
    """Cart model - synchronized cart between website and Telegram bot"""
    __tablename__ = 'carts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    product_item_id = db.Column(db.Integer, db.ForeignKey('product_items.id', ondelete='CASCADE'), nullable=False)
    quantity = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('User', backref='cart_items')
    product_item = db.relationship('ProductItem', backref='cart_items')
    
    def __repr__(self):
        return f'<Cart user_id={self.user_id} product_item_id={self.product_item_id} quantity={self.quantity}>'


class Notification(db.Model):
    """Notification model - for event-driven notifications (Phase 2)"""
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    type = db.Column(db.String(50), nullable=False, index=True)  # 'order_created', 'order_completed', 'balance_replenished', 'key_expires_soon', 'promo_personal'
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False)  # 'email', 'telegram', 'both'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relationships
    user = db.relationship('User', backref='notifications')
    
    def __repr__(self):
        return f'<Notification {self.type} for user {self.user_id}>'


class LoyaltyLevel(db.Model):
    """Loyalty level model - DarkZone Status system"""
    __tablename__ = 'loyalty_levels'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    threshold = db.Column(db.Integer, default=0, nullable=False)  # Threshold in rubles
    cashback_percent = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)  # Cashback percentage from deposits
    referral_percent = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)  # Referral commission percentage
    discount_percent = db.Column(db.Numeric(5, 2), default=0.00, nullable=False)  # Discount percentage on purchases
    position = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Legacy field for compatibility
    min_total_spent = db.Column(db.Numeric(10, 2), default=0.00, nullable=False)
    
    # Relationships
    users = db.relationship('User', backref='loyalty_level', lazy='dynamic', foreign_keys='User.loyalty_level_id')
    
    def __repr__(self):
        return f'<LoyaltyLevel {self.name}>'


# Support Chat Models
class Chat(db.Model):
    """Support chat model"""
    __tablename__ = 'chats'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Nullable for guest users
    guest_email = db.Column(db.String(120), nullable=True)  # For guest users
    guest_name = db.Column(db.String(100), nullable=True)  # For guest users
    status = db.Column(db.String(20), default='open', nullable=False)  # 'open', 'in_progress', 'resolved', 'closed'
    priority = db.Column(db.String(20), default='normal', nullable=False)  # 'low', 'normal', 'high', 'urgent'
    subject = db.Column(db.String(200), nullable=True)
    rating = db.Column(db.Integer, nullable=True)  # 1-5 rating from user
    rating_comment = db.Column(db.Text, nullable=True)
    assigned_to_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Admin/operator assigned
    last_message_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    
    # Relationships
    user = db.relationship('User', foreign_keys=[user_id], backref='chats')
    assigned_to = db.relationship('User', foreign_keys=[assigned_to_id], backref='assigned_chats')
    messages = db.relationship('ChatMessage', backref='chat', lazy='dynamic', order_by='ChatMessage.created_at', cascade='all, delete-orphan')
    attachments = db.relationship('ChatAttachment', backref='chat', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Chat {self.id}>'
    
    def get_unread_count(self, user_id=None):
        """Get unread message count for user"""
        if user_id:
            return self.messages.filter(
                ChatMessage.read_at.is_(None),
                ChatMessage.user_id != user_id
            ).count()
        return self.messages.filter(ChatMessage.read_at.is_(None)).count()
    
    def get_last_message(self):
        """Get last message in chat"""
        return self.messages.order_by(ChatMessage.created_at.desc()).first()


class ChatMessage(db.Model):
    """Chat message model"""
    __tablename__ = 'chat_messages'
    
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # Nullable for system messages
    is_admin = db.Column(db.Boolean, default=False, nullable=False)  # True if message from admin/operator
    message = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default='text', nullable=False)  # 'text', 'system', 'file', 'template'
    read_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('User', backref='chat_messages')
    attachments = db.relationship('ChatAttachment', backref='message', lazy='dynamic', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<ChatMessage {self.id}>'
    
    def mark_as_read(self):
        """Mark message as read"""
        if not self.read_at:
            self.read_at = datetime.utcnow()
            db.session.commit()


class ChatAttachment(db.Model):
    """Chat attachment model"""
    __tablename__ = 'chat_attachments'
    
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chats.id'), nullable=False, index=True)
    message_id = db.Column(db.Integer, db.ForeignKey('chat_messages.id'), nullable=True, index=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)  # Size in bytes
    mime_type = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<ChatAttachment {self.id}>'


class ChatTemplate(db.Model):
    """Chat response template model"""
    __tablename__ = 'chat_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=True)  # 'greeting', 'common', 'technical', etc.
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationships
    created_by = db.relationship('User', backref='chat_templates')
    
    def __repr__(self):
        return f'<ChatTemplate {self.id}>'


class ChatOperator(db.Model):
    """Chat operator model for tracking operator status"""
    __tablename__ = 'chat_operators'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    is_online = db.Column(db.Boolean, default=False, nullable=False)
    last_online_at = db.Column(db.DateTime, nullable=True)
    active_chats_count = db.Column(db.Integer, default=0, nullable=False)
    
    # Relationships
    user = db.relationship('User', backref='chat_operator_profile', lazy=True)
    
    def __repr__(self):
        return f'<ChatOperator {self.id} - User {self.user_id}>'


class Promotion(db.Model):
    """Promotion model - for time-bound discounts and special offers"""
    __tablename__ = 'promotions'
    
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    promo_type = db.Column(db.String(20), nullable=False)  # 'discount', 'free_keys'
    discount_value = db.Column(db.Numeric(10, 2), default=0.00)  # Percentage or fixed amount
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationship
    product = db.relationship('Product', back_populates='promotions')
    
    def __repr__(self):
        return f'<Promotion {self.name} for Product {self.product_id}>'

    def is_currently_active(self):
        """Check if promotion is active based on status and dates"""
        from datetime import datetime
        now = datetime.utcnow()
        return self.is_active and self.start_date <= now <= self.end_date


class AuditLog(db.Model):
    """Audit log model for tracking administrator actions"""
    __tablename__ = 'audit_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    action = db.Column(db.String(100), nullable=False, index=True)  # 'ban_user', 'change_price', 'delete_product', etc.
    target_type = db.Column(db.String(50), nullable=True)  # 'user', 'product', 'setting', etc.
    target_id = db.Column(db.String(100), nullable=True)
    details = db.Column(db.Text, nullable=True)  # JSON or descriptive text
    ip_address = db.Column(db.String(45), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relationships
    user = db.relationship('User', backref='admin_actions')
    
    def __repr__(self):
        return f'<AuditLog {self.action} by {self.user_id}>'


class LoginLog(db.Model):
    """Log of user login events for security history"""
    __tablename__ = 'login_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    ip_address = db.Column(db.String(45), nullable=False)
    user_agent = db.Column(db.String(255), nullable=True)
    status = db.Column(db.String(20), default='success')  # 'success', 'failed'
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Relationship
    user = db.relationship('User', backref='login_history')
    
    @property
    def device_info(self):
        """Parse user agent to return a friendly device/browser string"""
        if not self.user_agent:
            return '-'
        
        ua = self.user_agent
        
        # Determine OS
        os = 'Unknown OS'
        if 'Windows' in ua: os = 'Windows'
        elif 'Android' in ua: os = 'Android'
        elif 'iPhone' in ua or 'iPad' in ua: os = 'iOS'
        elif 'Macintosh' in ua: os = 'macOS'
        elif 'Linux' in ua: os = 'Linux'
        
        # Determine Browser
        browser = 'Browser'
        if 'YaBrowser' in ua: browser = 'Yandex'
        elif 'Edg' in ua: browser = 'Edge'
        elif 'Chrome' in ua: browser = 'Chrome'
        elif 'Firefox' in ua: browser = 'Firefox'
        elif 'Safari' in ua: browser = 'Safari'
        elif 'Opera' in ua or 'OPR' in ua: browser = 'Opera'
        
        return f"{os} - {browser}"

    def __repr__(self):
        return f'<LoginLog user={self.user_id} ip={self.ip_address}>'


class ProductWatch(db.Model):
    """Product watch model for price and stock alerts"""
    __tablename__ = 'product_watches'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id', ondelete='CASCADE'), nullable=False, index=True)
    target_price = db.Column(db.Numeric(10, 2), nullable=True)  # Notify if price drops below this
    notify_on_stock = db.Column(db.Boolean, default=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    user = db.relationship('User', backref='watched_products')
    product = db.relationship('Product', backref='watchers')
    
    def __repr__(self):
        return f'<ProductWatch user={self.user_id} product={self.product_id}>'


class Article(db.Model):
    """Article model for blog/news/about section"""
    __tablename__ = 'articles'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False, index=True)
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    position = db.Column(db.Integer, default=0, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    def __repr__(self):
        return f'<Article {self.title}>'


class DiscordGameNotification(db.Model):
    """Users can subscribe to game status updates in Discord"""
    __tablename__ = 'discord_game_notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True) # Linked website user
    discord_id = db.Column(db.BigInteger, nullable=False, index=True)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    game = db.relationship('Game', backref='discord_subscribers')
    user = db.relationship('User', backref='discord_subscriptions')


class Giveaway(db.Model):
    """Discord giveaway management"""
    __tablename__ = 'giveaways'
    
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.BigInteger, unique=True, nullable=False)
    channel_id = db.Column(db.BigInteger, nullable=False)
    prize = db.Column(db.String(255), nullable=False)
    winners_count = db.Column(db.Integer, default=1)
    end_time = db.Column(db.DateTime, nullable=False)
    is_ended = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Giveaway {self.prize} ended={self.is_ended}>'