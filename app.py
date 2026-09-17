import csv
import io
import random
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)

# Default global state structure
DEFAULT_STATE = {
    'inCombat': False,
    'roundNum': 1,
    'maxStr': 40,
    'currentStr': 40,
    'baseWeaponDice': 8,
    'activeWeaponDice': 8,
    'expectedDice': 8,
    'minStrReq': 15,
    'currentAdds': 55,
    'berserkActive': False,
    'hasInsaneStrengthFeat': True,
    'insaneStrengthActive': False,
    'spentSpiteThisRound': 0,
    'damageResolvedThisRound': False,
    'abilityActivatedThisRound': False,
    'minStrWarningTriggered': False,
    'currentDiceSum': 0,
    'currentSpiteTotal': 0,
    'finalDamageThisRound': 0,
    'lastDamageMessage': "",
    'pendingSets': [],
    'currentSetInfo': None,
    'rollHistory': [],
    'historyLog': [],
    'activePhase': 'damage',
    'summaryMsg': ""
}

# In-memory session state store
state_store = dict(DEFAULT_STATE)


def get_state():
    return state_store


def save_state(new_state):
    global state_store
    state_store = new_state


def parse_dice_input(dice_str, expected_count):
    if not dice_str:
        return [], f"Expected {expected_count} dice values."
    parts = dice_str.strip().split()
    if len(parts) != expected_count:
        return [], f"Expected exactly {expected_count} dice values, but got {len(parts)}."
    
    dice = []
    for p in parts:
        try:
            val = int(p)
            if val < 1 or val > 6:
                return [], "Dice values must be between 1 and 6."
            dice.append(val)
        except ValueError:
            return [], "Invalid dice value entered."
    return dice, None


def count_spite(dice_list):
    return dice_list.count(1)


def find_sets(dice_list):
    counts = {}
    for d in dice_list:
        counts[d] = counts.get(d, 0) + 1
    
    sets = []
    # 1s never roll over (Spite damage only)
    for val in sorted(counts.keys()):
        if val != 1 and counts[val] >= 2:
            sets.append({'val': val, 'count': counts[val]})
    return sets


def compute_and_save_final_damage(state):
    adds = state['currentAdds']
    if state['insaneStrengthActive']:
        adds += state['currentStr']
    
    total = state['currentDiceSum'] + adds
    state['finalDamageThisRound'] = total
    
    spite_msg = f" (Dealt {state['currentSpiteTotal']} direct Spite Damage!)" if state['currentSpiteTotal'] > 0 else ""
    state['lastDamageMessage'] = f"Rolled a total dice sum of {state['currentDiceSum']} + {adds} adds = {total} Total Damage!{spite_msg}"


def finalize_round_history(state, str_lost=0):
    breakdown_parts = []
    for h in state['rollHistory']:
        if h.get('dice') is not None:
            breakdown_parts.append(f"{h['phase']}: [{', '.join(map(str, h['dice']))}] (={h['sum']})")
        else:
            breakdown_parts.append(h['phase'])

    breakdown_str = " ➔ ".join(breakdown_parts)

    state['historyLog'].append({
        'round': state['roundNum'],
        'dice_breakdown': breakdown_str,
        'dice_sum': state['currentDiceSum'],
        'spite': state['currentSpiteTotal'],
        'adds': state['currentAdds'],
        'total_damage': state['finalDamageThisRound'],
        'str_lost': str_lost,
        'str_remaining': state['currentStr'],
        'adds_next': state['currentAdds']
    })


@app.route('/')
def index():
    state = get_state()
    context_extras = {'state': state}
    return render_template('index.html', state=state, ctx=context_extras)


@app.route('/api/start_combat', methods=['POST'])
def start_combat():
    data = request.json
    state = get_state()

    max_str = int(data.get('max_str', 40))
    base_dice = int(data.get('base_weapon_dice', 8))
    min_str = int(data.get('min_str_req', 15))
    initial_adds = int(data.get('initial_adds', 55))
    already_berserk = bool(data.get('already_berserk', False))
    has_insane = bool(data.get('has_insane_strength', True))

    state.update({
        'inCombat': True,
        'roundNum': 1,
        'maxStr': max_str,
        'currentStr': max_str,
        'baseWeaponDice': base_dice,
        'activeWeaponDice': base_dice,
        'expectedDice': base_dice,
        'minStrReq': min_str,
        'currentAdds': initial_adds,
        'berserkActive': already_berserk,
        'hasInsaneStrengthFeat': has_insane,
        'insaneStrengthActive': False,
        'spentSpiteThisRound': 0,
        'damageResolvedThisRound': False,
        'abilityActivatedThisRound': False,
        'minStrWarningTriggered': False,
        'currentDiceSum': 0,
        'currentSpiteTotal': 0,
        'finalDamageThisRound': 0,
        'lastDamageMessage': "",
        'pendingSets': [],
        'currentSetInfo': None,
        'rollHistory': [],
        'historyLog': [],
        'activePhase': 'damage',
        'summaryMsg': ""
    })

    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/update_dice_pool', methods=['POST'])
def update_dice_pool():
    state = get_state()
    data = request.json
    dice_pool = int(data.get('dice_pool', state['expectedDice']))
    state['activeWeaponDice'] = dice_pool
    state['expectedDice'] = dice_pool
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/roll_damage', methods=['POST'])
def roll_damage():
    state = get_state()
    data = request.json
    auto_roll = data.get('auto_roll', False)

    is_initial_roll = not state['currentSetInfo'] and len(state['rollHistory']) == 0

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

    if state['currentSetInfo']:
        state['currentSetInfo'] = None

    # ONLY detect set explosions if Berserk mode is active!
    if state['berserkActive']:
        new_sets = find_sets(dice)
        if is_initial_roll:
            state['pendingSets'] = new_sets
        else:
            state['pendingSets'].extend(new_sets)

        if state['pendingSets']:
            next_set = state['pendingSets'].pop(0)
            state['currentSetInfo'] = next_set
            state['expectedDice'] = next_set['count']
    else:
        state['pendingSets'] = []
        state['currentSetInfo'] = None

    compute_and_save_final_damage(state)
    state['damageResolvedThisRound'] = True

    # Phase Routing
    total_spent = state['spentSpiteThisRound'] + (3 if state['insaneStrengthActive'] else 0)
    available_spite = max(0, state['currentSpiteTotal'] - total_spent)
    can_afford_berserk = (not state['berserkActive']) and (available_spite >= 2)
    can_afford_insane = state['hasInsaneStrengthFeat'] and (state['insaneStrengthActive'] or available_spite >= 3)

    if state['berserkActive']:
        if state['pendingSets'] or state['currentSetInfo'] or can_afford_insane:
            state['activePhase'] = 'damage'
        else:
            state['activePhase'] = 'str_loss'
    else:
        if can_afford_berserk or can_afford_insane:
            state['activePhase'] = 'damage'
        else:
            state['activePhase'] = 'results'

    save_state(state)
    return jsonify({
        'status': 'damage_done',
        'final_total': state['finalDamageThisRound'],
        'message': state['lastDamageMessage'],
        'state': state
    })


@app.route('/api/activate_berserk', methods=['POST'])
def activate_berserk():
    state = get_state()
    if state['berserkActive'] and state['spentSpiteThisRound'] == 2:
        # Backing out of Berserk
        state['berserkActive'] = False
        state['spentSpiteThisRound'] -= 2
        state['pendingSets'] = []
        state['currentSetInfo'] = None
    else:
        # Activating Berserk
        state['berserkActive'] = True
        state['spentSpiteThisRound'] += 2
        state['abilityActivatedThisRound'] = True

        # Re-scan all dice rolled in the current round for valid explosion sets (ignoring 1s)
        recalculated_sets = []
        for h in state['rollHistory']:
            dice = h.get('dice')
            if dice:
                recalculated_sets.extend(find_sets(dice))

        state['pendingSets'] = recalculated_sets

    compute_and_save_final_damage(state)
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/toggle_insane_strength', methods=['POST'])
def toggle_insane_strength():
    state = get_state()
    if state['insaneStrengthActive']:
        state['insaneStrengthActive'] = False
    else:
        state['insaneStrengthActive'] = True
        state['abilityActivatedThisRound'] = True

    compute_and_save_final_damage(state)
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/advance_after_ability', methods=['POST'])
def advance_after_ability():
    state = get_state()
    state['abilityActivatedThisRound'] = False

    if state['berserkActive'] and state['spentSpiteThisRound'] == 2:
        already_logged = any("Activated Berserk" in h.get('phase', '') for h in state['rollHistory'])
        if not already_logged:
            state['rollHistory'].append({
                'phase': "🔥 Activated Berserk (Spent 2 Spite)",
                'dice': None,
                'sum': 0,
                'spite': 0
            })

    if state['insaneStrengthActive']:
        already_logged = any("Insane Strength" in h.get('phase', '') for h in state['rollHistory'])
        if not already_logged:
            state['rollHistory'].append({
                'phase': "⚡ Activated Insane Strength (Spent 3 Spite)",
                'dice': None,
                'sum': 0,
                'spite': 0
            })

    if state['berserkActive'] and state['pendingSets']:
        next_set = state['pendingSets'].pop(0)
        state['currentSetInfo'] = next_set
        state['expectedDice'] = next_set['count']
        state['activePhase'] = 'damage'
    elif state['berserkActive']:
        state['activePhase'] = 'str_loss'
    else:
        state['activePhase'] = 'results'

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
    new_adds = max(0, state['currentAdds'] - str_lost)
    state['currentAdds'] = new_adds

    warning_msg = None
    if new_str < state['minStrReq']:
        if not state['minStrWarningTriggered']:
            warning_msg = f"⚠️ WARNING: Your Strength ({new_str}) fell below weapon minimum requirement ({state['minStrReq']})! Please adjust your dice pool if needed."
            state['minStrWarningTriggered'] = True
    else:
        state['minStrWarningTriggered'] = False

    finalize_round_history(state, str_lost=str_lost)

    if new_str <= 0:
        state['activePhase'] = 'summary'
        state['summaryMsg'] = "💀 Your Strength reached 0! You have fallen unconscious from exhaustion."
        save_state(state)
        return jsonify({
            'status': 'unconscious',
            'message': state['summaryMsg'],
            'warning_msg': warning_msg,
            'expected_dice': state['expectedDice'],
            'state': state
        })

    state['activePhase'] = 'results'
    save_state(state)

    return jsonify({
    'status': 'ok',
    'warning_msg': warning_msg,
    'expected_dice': state['activeWeaponDice'],
    'state': state
})


@app.route('/api/adjust_str', methods=['POST'])
def adjust_str():
    state = get_state()
    data = request.json
    delta = int(data.get('delta', 0))
    new_str = max(0, state['currentStr'] + delta)
    state['currentStr'] = new_str

    warning_msg = None
    if new_str < state['minStrReq']:
        if not state['minStrWarningTriggered']:
            warning_msg = f"⚠️ WARNING: Your Strength ({new_str}) fell below weapon minimum requirement ({state['minStrReq']})! Please adjust your dice pool if needed."
            state['minStrWarningTriggered'] = True
    else:
        state['minStrWarningTriggered'] = False

    save_state(state)
    return jsonify({
    'status': 'ok',
    'warning_msg': warning_msg,
    'expected_dice': state['activeWeaponDice'],
    'state': state
})


@app.route('/api/adjust_adds', methods=['POST'])
def adjust_adds():
    state = get_state()
    data = request.json
    delta = int(data.get('delta', 0))
    state['currentAdds'] = max(0, state['currentAdds'] + delta)
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/proceed_non_berserk', methods=['POST'])
def proceed_non_berserk():
    state = get_state()
    finalize_round_history(state, str_lost=0)
    
    state['roundNum'] += 1
    state['insaneStrengthActive'] = False
    state['spentSpiteThisRound'] = 0
    state['damageResolvedThisRound'] = False
    state['abilityActivatedThisRound'] = False
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


@app.route('/api/next_round', methods=['POST'])
def next_round():
    state = get_state()
    data = request.json or {}

    stop_requested = data.get('stopped', False)
    iq_passed = data.get('iq_passed', False)

    state['roundNum'] += 1
    state['insaneStrengthActive'] = False
    state['spentSpiteThisRound'] = 0
    state['damageResolvedThisRound'] = False
    state['abilityActivatedThisRound'] = False
    state['lastDamageMessage'] = ""
    state['expectedDice'] = state['activeWeaponDice']
    state['currentDiceSum'] = 0
    state['currentSpiteTotal'] = 0
    state['finalDamageThisRound'] = 0
    state['pendingSets'] = []
    state['currentSetInfo'] = None
    state['rollHistory'] = []
    state['activePhase'] = 'damage'

    if stop_requested and iq_passed:
        state['berserkActive'] = False

    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/reset_combat', methods=['POST'])
def reset_combat():
    save_state(dict(DEFAULT_STATE))
    return jsonify({'status': 'ok'})


@app.route('/api/export_csv', methods=['GET'])
def export_csv():
    state = get_state()
    history = state.get('historyLog', [])

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        'Round', 
        'Total Damage Dealt', 
        'Spite (1s)', 
        'STR Lost', 
        'STR Left', 
        'Adds Next Round',
        'Dice Breakdown'
    ])

    for row in history:
        writer.writerow([
            row.get('round'),
            row.get('total_damage'),
            row.get('spite'),
            row.get('str_lost'),
            row.get('str_remaining'),
            row.get('adds_next'),
            row.get('dice_breakdown')
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=berserker_combat_log.csv"}
    )


if __name__ == '__main__':
    app.run(debug=True)