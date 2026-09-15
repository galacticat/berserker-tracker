import os
import random
from collections import Counter
from flask import Flask, render_template, request, jsonify, session

app = Flask(__name__)

app.config['SECRET_KEY'] = 'berserker_secret_key_fixed_98765'
app.config['SESSION_COOKIE_NAME'] = 'berserker_session'

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

def get_default_state():
    return {
        'inCombat': False,
        'maxStr': 40,
        'currentStr': 40,
        'baseWeaponDice': 8,
        'activeWeaponDice': 8,
        'minStrReq': 15,
        'currentAdds': 55,
        'berserkActive': False,
        'hasInsaneStrengthFeat': True,
        'insaneStrengthActive': False,
        'spentSpiteThisRound': 0,
        'roundNum': 1,
        'expectedDice': 8,
        'currentDiceSum': 0,
        'currentSpiteTotal': 0,
        'finalDamageThisRound': 0,
        'lastDamageMessage': "",
        'damageResolvedThisRound': False,
        'minStrWarningTriggered': False,
        'pendingSets': [],
        'currentSetInfo': None,
        'rollHistory': [],
        'historyLog': [],
        'activePhase': 'damage'
    }

def get_state():
    if 'state' not in session:
        session['state'] = get_default_state()
    return session['state']

def save_state(state):
    session['state'] = state
    session.modified = True

def parse_dice_input(input_str, expected_count):
    parts = input_str.strip().replace(',', ' ').split()
    if len(parts) != expected_count:
        return None, f"Expected exactly {expected_count} dice values, but got {len(parts)}."
    
    dice = []
    for p in parts:
        try:
            val = int(p)
            if val < 1 or val > 6:
                return None, f"Dice value '{p}' is invalid. Must be between 1 and 6."
            dice.append(val)
        except ValueError:
            return None, f"Invalid value '{p}'. Must be numbers between 1 and 6."
    
    return dice, None

def count_spite(dice_list):
    return dice_list.count(1)

def find_sets(dice_list):
    counts = Counter(dice_list)
    sets = []
    for val, cnt in counts.items():
        if val != 1 and cnt >= 2:
            sets.append({'val': val, 'count': cnt})
    return sets

@app.route('/')
def index():
    state = get_state()
    return render_template('index.html', state=state)

@app.route('/api/start_combat', methods=['POST'])
def start_combat():
    data = request.json
    state = get_default_state()
    state['inCombat'] = True
    state['maxStr'] = int(data.get('max_str', 40))
    state['currentStr'] = state['maxStr']
    state['baseWeaponDice'] = int(data.get('base_weapon_dice', 8))
    state['activeWeaponDice'] = state['baseWeaponDice']
    state['minStrReq'] = int(data.get('min_str_req', 15))
    state['currentAdds'] = int(data.get('initial_adds', 55))
    state['berserkActive'] = bool(data.get('already_berserk', False))
    state['hasInsaneStrengthFeat'] = bool(data.get('has_insane_strength', True))
    state['expectedDice'] = state['activeWeaponDice']
    state['minStrWarningTriggered'] = False
    state['activePhase'] = 'damage'

    save_state(state)
    return jsonify({'status': 'ok', 'state': state})

@app.route('/api/adjust_str', methods=['POST'])
def adjust_str():
    state = get_state()
    data = request.json
    try:
        delta = int(data.get('delta', 0))
        new_str = max(0, state['currentStr'] + delta)
        state['currentStr'] = new_str
        
        warning_msg = None
        if new_str < state['minStrReq']:
            if not state['minStrWarningTriggered']:
                warning_msg = f"⚠️ WARNING: Your Strength ({new_str}) fell below weapon minimum requirement ({state['minStrReq']})! Please adjust your dice pool if needed."
                state['minStrWarningTriggered'] = True
        else:
            # Reset warning trigger if STR rises back above minimum
            state['minStrWarningTriggered'] = False

        save_state(state)
        return jsonify({'status': 'ok', 'warning_msg': warning_msg, 'state': state})
    except ValueError:
        return jsonify({'message': 'Invalid adjustment amount.'}), 400

@app.route('/api/adjust_adds', methods=['POST'])
def adjust_adds():
    state = get_state()
    data = request.json
    try:
        delta = int(data.get('delta', 0))
        state['currentAdds'] = max(0, state['currentAdds'] + delta)
        save_state(state)
        return jsonify({'status': 'ok', 'state': state})
    except ValueError:
        return jsonify({'message': 'Invalid adjustment amount.'}), 400

@app.route('/api/update_dice_pool', methods=['POST'])
def update_dice_pool():
    state = get_state()
    data = request.json
    try:
        new_dice = int(data.get('dice_pool', state['activeWeaponDice']))
        if new_dice < 1:
            return jsonify({'message': 'Dice pool must be at least 1.'}), 400
        state['activeWeaponDice'] = new_dice
        state['expectedDice'] = new_dice
        save_state(state)
        return jsonify({'status': 'ok', 'state': state})
    except ValueError:
        return jsonify({'message': 'Invalid dice pool value.'}), 400

def finalize_non_berserk_round(state):
    breakdown_strs = [f"{h['phase']}: [{', '.join(map(str, h['dice']))}] (={h['sum']})" for h in state['rollHistory']]
    effective_adds = state['currentAdds'] + (state['currentStr'] if state['insaneStrengthActive'] else 0)
    
    history_entry = {
        'round': state['roundNum'],
        'dice_breakdown': " ➔ ".join(breakdown_strs),
        'dice_sum': state['currentDiceSum'],
        'spite': state['currentSpiteTotal'],
        'adds': f"+{effective_adds}",
        'total_damage': state['finalDamageThisRound'],
        'str_lost': 0,
        'str_remaining': state['currentStr'],
        'adds_next': f"+{state['currentAdds']}"
    }
    state['historyLog'].append(history_entry)

    state['roundNum'] += 1
    state['insaneStrengthActive'] = False
    state['spentSpiteThisRound'] = 0
    state['damageResolvedThisRound'] = False
    state['expectedDice'] = state['activeWeaponDice']
    state['currentDiceSum'] = 0
    state['currentSpiteTotal'] = 0
    state['finalDamageThisRound'] = 0
    state['rollHistory'] = []
    state['activePhase'] = 'damage'

@app.route('/api/roll_damage', methods=['POST'])
def roll_damage():
    state = get_state()
    data = request.json
    auto_roll = data.get('auto_roll', False)

    if not state['currentSetInfo']:
        state['expectedDice'] = int(data.get('expected_dice', state['expectedDice']))

    if auto_roll:
        dice = [random.randint(1, 6) for _ in range(state['expectedDice'])]
    else:
        dice_input = data.get('dice_input', '')
        dice, err = parse_dice_input(dice_input, state['expectedDice'])
        if err:
            return jsonify({'message': err}), 400

    roll_sum = sum(dice)
    spite = count_spite(dice)
    
    state['currentDiceSum'] += roll_sum
    state['currentSpiteTotal'] += spite

    phase_name = "Base Weapon Roll" if not state['currentSetInfo'] else f"Roll-Over for Sets of [{state['currentSetInfo']['val']}]s"
    state['rollHistory'].append({
        'phase': phase_name,
        'dice': dice,
        'sum': roll_sum,
        'spite': spite
    })

    if state['berserkActive']:
        sets = find_sets(dice)
        if sets:
            state['pendingSets'].extend(sets)

        if state['pendingSets']:
            next_set = state['pendingSets'].pop(0)
            state['currentSetInfo'] = next_set
            state['expectedDice'] = next_set['count']
            state['activePhase'] = 'damage'
            save_state(state)
            
            return jsonify({
                'status': 'rollover',
                'message': f"Matching set found! You rolled {next_set['count']}x [{next_set['val']}s]. Roll {next_set['count']} additional dice!",
                'action_instruction': f"Roll {next_set['count']} additional d6 for your matching set of {next_set['val']}s.",
                'state': state
            })

    effective_adds = state['currentAdds'] + (state['currentStr'] if state['insaneStrengthActive'] else 0)
    final_total = state['currentDiceSum'] + effective_adds
    state['finalDamageThisRound'] = final_total
    state['damageResolvedThisRound'] = True
    
    spite_msg = f" (Dealt {state['currentSpiteTotal']} direct Spite Damage!)" if state['currentSpiteTotal'] > 0 else ""
    state['lastDamageMessage'] = f"Rolled a total dice sum of {state['currentDiceSum']} + {effective_adds} adds = {final_total} Total Damage!{spite_msg}"

    if state['berserkActive']:
        state['activePhase'] = 'str_loss'
    else:
        has_spite_options = (state['currentSpiteTotal'] >= 2) or (state['hasInsaneStrengthFeat'] and state['currentSpiteTotal'] >= 3)
        if has_spite_options:
            state['activePhase'] = 'damage'
        else:
            finalize_non_berserk_round(state)

    save_state(state)
    return jsonify({
        'status': 'damage_done',
        'final_total': final_total,
        'message': state['lastDamageMessage'],
        'state': state
    })

@app.route('/api/proceed_non_berserk', methods=['POST'])
def proceed_non_berserk():
    state = get_state()
    if not state['berserkActive'] and state['damageResolvedThisRound']:
        finalize_non_berserk_round(state)
        save_state(state)
    return jsonify({'status': 'ok', 'state': state})

@app.route('/api/activate_berserk', methods=['POST'])
def activate_berserk():
    state = get_state()
    state['spentSpiteThisRound'] = 2
    state['berserkActive'] = True
    
    all_sets = []
    for h in state['rollHistory']:
        all_sets.extend(find_sets(h['dice']))

    if all_sets:
        state['pendingSets'] = all_sets
        next_set = state['pendingSets'].pop(0)
        state['currentSetInfo'] = next_set
        state['expectedDice'] = next_set['count']
        state['damageResolvedThisRound'] = False
        state['activePhase'] = 'damage'
        save_state(state)

        return jsonify({
            'status': 'rollover',
            'message': f"💥 BERSERK ACTIVATED! Retroactive Matching set found: {next_set['count']}x [{next_set['val']}s]. Roll {next_set['count']} additional dice!",
            'action_instruction': f"Roll {next_set['count']} additional d6 for your set of {next_set['val']}s.",
            'state': state
        })

    state['activePhase'] = 'str_loss'
    save_state(state)
    return jsonify({'status': 'activated', 'state': state})

@app.route('/api/toggle_insane_strength', methods=['POST'])
def toggle_insane_strength():
    state = get_state()
    state['insaneStrengthActive'] = not state['insaneStrengthActive']
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})

@app.route('/api/roll_str_loss', methods=['POST'])
def roll_str_loss():
    state = get_state()
    data = request.json
    auto_roll = data.get('auto_roll', False)

    if auto_roll:
        str_lost = random.randint(1, 6)
    else:
        try:
            str_lost = int(data.get('loss_val', 0))
            if str_lost < 1 or str_lost > 6:
                return jsonify({'message': 'STR loss must be between 1 and 6.'}), 400
        except ValueError:
            return jsonify({'message': 'Invalid STR loss number.'}), 400

    new_str = max(0, state['currentStr'] - str_lost)
    state['currentStr'] = new_str

    if not state['berserkActive']:
        new_adds = state['currentAdds']
        adds_change_text = f"+{new_adds}"
    else:
        new_adds = max(0, state['currentAdds'] - str_lost)
        adds_change_text = f"+{new_adds} (-{str_lost})"
        state['currentAdds'] = new_adds

    warning_msg = None
    if new_str < state['minStrReq']:
        if not state['minStrWarningTriggered']:
            warning_msg = f"⚠️ WARNING: Your Strength ({new_str}) fell below weapon minimum requirement ({state['minStrReq']})! Please adjust your dice pool if needed."
            state['minStrWarningTriggered'] = True
    else:
        state['minStrWarningTriggered'] = False

    breakdown_strs = []
    for h in state['rollHistory']:
        breakdown_strs.append(f"{h['phase']}: [{', '.join(map(str, h['dice']))}] (={h['sum']})")
    
    if state['spentSpiteThisRound'] > 0:
        breakdown_strs.append(f"[🔥 Activated Berserk ({state['spentSpiteThisRound']} Spite)]")

    history_entry = {
        'round': state['roundNum'],
        'dice_breakdown': " ➔ ".join(breakdown_strs),
        'dice_sum': state['currentDiceSum'],
        'spite': state['currentSpiteTotal'],
        'adds': f"+{state['currentAdds'] + str_lost}" if state['berserkActive'] else f"+{state['currentAdds']}",
        'total_damage': state['finalDamageThisRound'],
        'str_lost': str_lost if state['berserkActive'] else 0,
        'str_remaining': new_str,
        'adds_next': adds_change_text
    }
    
    state['historyLog'].append(history_entry)

    if state['berserkActive'] and new_str <= 0:
        state['activePhase'] = 'summary'
        save_state(state)
        return jsonify({
            'status': 'unconscious',
            'message': '💀 Your Strength dropped to 0! You fall unconscious from exhaustion.',
            'rest_turns_needed': state['maxStr'],
            'warning_msg': warning_msg,
            'state': state
        })

    state['activePhase'] = 'round_end' if state['berserkActive'] else 'damage'
    save_state(state)

    return jsonify({
        'status': 'ok',
        'warning_msg': warning_msg,
        'state': state
    })

@app.route('/api/next_round', methods=['POST'])
def next_round():
    state = get_state()
    data = request.json
    stopped = data.get('stopped', False)

    if stopped:
        state['berserkActive'] = False
        state['activePhase'] = 'summary'
        rest_needed = state['maxStr'] - state['currentStr']
        state['summaryMsg'] = f"✨ You snapped out of the berserk rage! You need {rest_needed} turn(s) of full rest to regain your Strength."
    else:
        state['roundNum'] += 1
        state['insaneStrengthActive'] = False
        state['spentSpiteThisRound'] = 0
        state['damageResolvedThisRound'] = False
        state['lastDamageMessage'] = ""
        state['expectedDice'] = state['activeWeaponDice']
        state['currentDiceSum'] = 0
        state['currentSpiteTotal'] = 0
        state['finalDamageThisRound'] = 0
        state['pendingSets'] = []
        state['currentSetInfo'] = None
        state['rollHistory'] = []
        state['activePhase'] = 'damage'

    save_state(state)
    return jsonify({'status': 'ok', 'state': state})

@app.route('/api/reset_combat', methods=['POST'])
def reset_combat():
    session.pop('state', None)
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)