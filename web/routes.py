from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
from data.models import Strategy, Coin, Trade, Alert, db

views = Blueprint('views', __name__)

@views.route('/')
def home():
    """Home page."""
    # Fetch data without user context
    strategies = Strategy.query.filter_by(is_active=True).all()
    recent_trades = Trade.query.order_by(Trade.timestamp.desc()).limit(5).all()
        return render_template('home.html', strategies=strategies, recent_trades=recent_trades)

@views.route('/dashboard')
def dashboard():
    """Dashboard page."""
    # Fetch all active strategies, coins, trades, alerts
    strategies = Strategy.query.filter_by(is_active=True).all()
    coins = Coin.query.all()
    coin_data = []
    for coin in coins:
        # Need alternative way to get position if paper_trading module relied on user_id
        # Assuming get_position can work without user_id or is adapted
        # position = paper_trading.get_position(coin.id) # Example adaptation
        position = None # Placeholder
        coin_data.append({
            'coin': coin,
            'position': position
        })
    
    recent_trades = Trade.query.order_by(Trade.timestamp.desc()).limit(10).all()
    
    # Need alternative way to get alerts if alert_system relied on user_id
    # alerts = alert_system.get_alerts() # Example adaptation
    alerts = Alert.query.filter_by(is_active=True).all() # Fetching all active alerts as example

    return render_template('dashboard.html', 
                         strategies=strategies,
                           coin_data=coin_data, 
                         recent_trades=recent_trades,
                         alerts=alerts)

@views.route('/strategy/create', methods=['GET', 'POST'])
def create_strategy():
    if request.method == 'POST':
        # Process form data
        name = request.form.get('name')
        description = request.form.get('description')
        # parameters = request.form.get('parameters') # Process JSON parameters
        # Create strategy without user_id
        new_strategy = Strategy(name=name, description=description, parameters={}) # Simplified
        db.session.add(new_strategy)
        db.session.commit()
        flash('Strategy created successfully!', 'success')
        return redirect(url_for('views.dashboard'))
    return render_template('create_strategy.html')

@views.route('/strategy/<int:strategy_id>/edit', methods=['GET', 'POST'])
def edit_strategy(strategy_id):
        strategy = Strategy.query.get_or_404(strategy_id)
    if request.method == 'POST':
        # Update strategy details
        strategy.name = request.form.get('name')
        strategy.description = request.form.get('description')
        # Update parameters
        strategy.is_active = 'is_active' in request.form
        db.session.commit()
        flash('Strategy updated successfully!', 'success')
        return redirect(url_for('views.dashboard'))
    return render_template('edit_strategy.html', strategy=strategy)

@views.route('/trade/execute', methods=['POST'])
def execute_trade():
    # Get data from form
    strategy_id = request.form.get('strategy_id')
    coin_id = request.form.get('coin_id')
    action = request.form.get('action')
    amount = request.form.get('amount')
    price = request.form.get('price') # Optional for market orders
    
    strategy = Strategy.query.get(strategy_id)
    coin = Coin.query.get(coin_id)
    
    if not strategy or not coin:
        flash('Invalid strategy or coin specified.', 'danger')
        return redirect(request.referrer or url_for('views.dashboard'))
        
    try:
        trade_amount = float(amount)
        trade_price = float(price) if price else None # Handle market order price logic elsewhere
        
        # Placeholder for actual trade execution service call
        # success, message = trading_service.execute_trade(
        #     strategy_id=strategy.id, 
        #     coin_id=coin.id, 
        #     action=action, 
        #     amount=trade_amount, 
        #     price=trade_price
        # )
        
        # Simulating success and logging trade
        success = True 
        message = f"Simulated {action} trade for {trade_amount} of {coin.symbol}"
        
        if success:
            new_trade = Trade(
                token_id=coin.id, # Assuming Coin ID maps to Token ID needed by Trade
                strategy_id=strategy.id,
                coin_id=coin.id,
                action=action.upper(),
                type=action.upper(), # Assuming action is BUY/SELL
                price=trade_price or 0, # Store executed price
                amount=trade_amount,
                total= (trade_price or 0) * trade_amount, # Store executed total
                status='COMPLETED' # Assume immediate completion for simulation
            )
            db.session.add(new_trade)
            db.session.commit()
            flash(f'Trade executed: {message}', 'success')
        else:
            flash(f'Trade failed: {message}', 'danger')
            
    except ValueError:
        flash('Invalid amount or price.', 'danger')
    except Exception as e:
        flash(f'An error occurred during trade execution: {e}', 'danger')
        # Log the error
        
    return redirect(request.referrer or url_for('views.dashboard'))

@views.route('/alerts')
def list_alerts():
    # alerts = alert_system.get_alerts()
    alerts = Alert.query.filter_by(is_active=True).all()
    return render_template('alerts.html', alerts=alerts)

@views.route('/alert/toggle/<int:alert_id>', methods=['POST'])
def toggle_alert(alert_id):
    # success = alert_system.toggle_alert(alert_id)
    alert = Alert.query.get(alert_id)
    if alert:
        alert.is_active = not alert.is_active
        db.session.commit()
        flash(f'Alert {"activated" if alert.is_active else "deactivated"}.', 'success')
        success = True
    else:
        flash('Alert not found.', 'danger')
        success = False
        
    if request.is_json:
        return jsonify({'success': success})
        else:
        return redirect(url_for('views.list_alerts'))

@views.route('/alert/delete/<int:alert_id>', methods=['POST'])
def delete_alert(alert_id):
    # success = alert_system.delete_alert(alert_id)
    alert = Alert.query.get(alert_id)
    if alert:
        db.session.delete(alert)
        db.session.commit()
        flash('Alert deleted.', 'success')
        success = True
        else:
        flash('Alert not found.', 'danger')
        success = False

    if request.is_json:
        return jsonify({'success': success})
        else:
        return redirect(url_for('views.list_alerts')) 