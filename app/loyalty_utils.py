"""
Utility functions for loyalty system and cashback
"""
from app import db
from app.models import User, LoyaltyLevel, Transaction
from datetime import datetime


def calculate_cashback(user, deposit_amount):
    """
    Calculate cashback amount for a deposit based on user's loyalty level
    
    Args:
        user: User object
        deposit_amount: Amount of deposit in rubles
    
    Returns:
        cashback_amount: Calculated cashback amount
        cashback_percent: Cashback percentage from user's level
    """
    # Get user's current cashback percentage (override or loyalty level default)
    cashback_percent = user.get_cashback_percent()
    
    # Calculate cashback: deposit_amount * (cashback_percent / 100)
    cashback_amount = float(deposit_amount) * (cashback_percent / 100)
    
    return cashback_amount, cashback_percent


def apply_cashback(user, deposit_amount, transaction_id=None):
    """
    Apply cashback to user's balance after deposit
    
    Args:
        user: User object
        deposit_amount: Amount of deposit in rubles
        transaction_id: Optional transaction ID for reference
    
    Returns:
        cashback_amount: Applied cashback amount
    """
    cashback_amount, cashback_percent = calculate_cashback(user, deposit_amount)
    
    if cashback_amount > 0:
        # Add cashback to user's balance
        user.balance = float(user.balance) + cashback_amount
        
        # Create transaction record for cashback
        cashback_transaction = Transaction(
            user_id=user.id,
            transaction_type='deposit',
            amount=cashback_amount,
            payment_method='cashback',
            status='completed',
            completed_at=datetime.utcnow()
        )
        db.session.add(cashback_transaction)
        db.session.commit()
        
        return cashback_amount
    
    return 0.0


def update_user_loyalty_level(user):
    """
    Update user's loyalty level based on total_spent
    
    Args:
        user: User object
    
    Returns:
        new_level: New loyalty level object or None if no change
    """
    total_spent = int(user.total_spent)
    
    # Get all active loyalty levels ordered by threshold (descending)
    levels = LoyaltyLevel.query.filter_by(is_active=True).order_by(
        LoyaltyLevel.threshold.desc()
    ).all()
    
    # Find the highest level the user qualifies for
    new_level = None
    for level in levels:
        if total_spent >= int(level.threshold):
            new_level = level
            break
    
    # If no level found, assign default (Гость)
    if not new_level:
        new_level = LoyaltyLevel.query.filter_by(name='Гость', is_active=True).first()
    
    # Update user's level if changed
    if new_level and user.loyalty_level_id != new_level.id:
        user.loyalty_level_id = new_level.id
        db.session.commit()
        return new_level
    
    return None


def get_user_cashback_percent(user):
    """
    Get current cashback percentage for user
    
    Args:
        user: User object
    
    Returns:
        cashback_percent: Cashback percentage
    """
    return user.get_cashback_percent()


def get_next_loyalty_level(user):
    """
    Get next loyalty level for user based on total_spent
    
    Args:
        user: User object
    
    Returns:
        next_level: Next loyalty level object or None
        progress: Progress percentage (0-100)
        remaining: Remaining amount to next level
    """
    total_spent = int(user.total_spent)
    
    # Get all active loyalty levels ordered by threshold (ascending)
    levels = LoyaltyLevel.query.filter_by(is_active=True).order_by(
        LoyaltyLevel.threshold.asc()
    ).all()
    
    # Find current level
    current_level = None
    if user.loyalty_level_id:
        current_level = LoyaltyLevel.query.get(user.loyalty_level_id)
    
    # Find next level
    next_level = None
    for level in levels:
        if level.threshold > total_spent:
            next_level = level
            break
    
    if not next_level:
        return None, 100, 0
    
    # Calculate progress
    if current_level:
        current_threshold = int(current_level.threshold)
    else:
        current_threshold = 0
    
    next_threshold = int(next_level.threshold)
    remaining = next_threshold - total_spent
    
    if next_threshold > current_threshold:
        progress = ((total_spent - current_threshold) / (next_threshold - current_threshold)) * 100
        progress = max(0, min(100, progress))  # Clamp between 0 and 100
    else:
        progress = 100
    
    return next_level, progress, remaining
