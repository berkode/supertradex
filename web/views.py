from flask import Blueprint, redirect, url_for, render_template, request, flash, jsonify
from .models import Coin, db
import json
from typing import Optional, cast
from supertradex.strategies import strategy
from supertradex.utils import check_running

views = Blueprint('views', __name__)

@views.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        coin: Optional[str] = request.form.get('coin')
        pair: Optional[str] = request.form.get('pair')
        timeframe: Optional[str] = request.form.get('timeframe')
        fiat_limit: Optional[str] = request.form.get('fiat_limit')
        
        if not all([coin, pair, timeframe, fiat_limit]):
            flash('Please fill in all fields.', category='error')
            return render_template("home.html")
            
        try:
            fiat_limit_int = int(cast(str, fiat_limit))
        except ValueError:
            flash('Fiat limit must be a number.', category='error')
            return render_template("home.html")
        
        coin = cast(str, coin)
        if len(coin) < 1:
            flash('Coin name empty or too short!', category='error')
        else:
            new_coin = Coin(
                coin=coin,
                pair=cast(str, pair),
                timeframe=cast(str, timeframe),
                fiat_limit=fiat_limit_int,
            )
            db.session.add(new_coin)
            db.session.commit()
            flash('Coin added!', category='success')
            
    return render_template("home.html")

@views.route('/delete-coin', methods=['POST'])
def delete_coin():
    try:
        coin = json.loads(request.data)
        coinId = coin['coinId']
        coin = Coin.query.get(coinId)
        if coin:
            db.session.delete(coin)
            db.session.commit()
            flash('Coin deleted!', category='success')
    except (json.JSONDecodeError, KeyError):
        flash('Invalid request data.', category='error')
    return jsonify({})

@views.route('/run-strategy', methods=['POST'])
def run_strategy():
    try:
        coin = json.loads(request.data)
        coinId = coin['coinId']
        coin = Coin.query.get(coinId)
        if coin:
            coin = strategy(coin)
            flash('Strategy running!', category='success')
    except (json.JSONDecodeError, KeyError):
        flash('Invalid request data.', category='error')
    return jsonify({})

@views.route('/stop-strategy', methods=['POST'])
def stop_strategy():
    try:
        coin = json.loads(request.data)
        coinId = coin['coinId']
        coin = Coin.query.get(coinId)
        if coin:
            setattr(coin, 'strategy_running', False)
            db.session.commit()
            flash('Coinpair stopped!', category='success')
    except (json.JSONDecodeError, KeyError):
        flash('Invalid request data.', category='error')
    return jsonify({})

@views.route('/loop-strategy', methods=['POST', 'GET'])
def loop_strategy():
    coins = check_running()
    return redirect(url_for('views.home'))

@views.route('/google51d4ed7d1c10e7cb.html', methods=['GET'])
def google_authentication():
    return render_template("google51d4ed7d1c10e7cb.html") 