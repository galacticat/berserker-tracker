import csv
import io
import random
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)

# Default global state structure
DEFAULT_STATE = {
    'inCombat': False,
    'roundNum': 1,
    'level': 1,
    'iq': 12,
    'maxStr': 40,
    'currentStr': 40,
    'baseWeaponDice': 7,
    'activeWeaponDice': 7,
    'expectedDice': 7,
    'minStrReq': 24,
    'currentAdds': 55,
    'berserkActive': False,
    'hasInsaneStrengthFeat': True,
    'hasStunningBlowFeat': True,
    'hasSunflameFeat': True,
    'insaneStrengthActive': False,
    'stunningBlowActive': False,
    'sunflameActivatedThisRound': False,
    'sunflameTotalSpent': 0,
    'sunflamePendingDice': 0,
    'sunflamePostCombatPhase': False,
    'sunflameActiveRoll': False,
    'sunflameBonusSpiteAvailable': 0,
    'spentSpiteThisRound': 0,
    'damageResolvedThisRound': False,
    'abilityActivatedThisRound': False,
    'minStrWarningTriggered': False,
    'currentDiceSum': 0,
    'currentFireDiceSum': 0,
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


def get_total_spent_spite(state):
    return (
        state.get('spentSpiteThisRound', 0)
        + (3 if state.get('insaneStrengthActive', False) else 0)
        + (2 if state.get('stunningBlowActive', False) else 0)
        + state.get('sunflameTotalSpent', 0)
    )


def get_available_spite(state):
    return max(0, state.get('currentSpiteTotal', 0) - get_total_spent_spite(state))


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

    fire_dmg = state.get('currentFireDiceSum', 0)
    physical_dice_sum = state['currentDiceSum'] - fire_dmg
    net_spite = get_available_spite(state)

    if fire_dmg > 0:
        msg = (
            f"Rolled {physical_dice_sum} weapon dice + {fire_dmg} Sunflame fire damage + {adds} adds = "
            f"{total} Total Damage!"
        )
    else:
        msg = f"Rolled a total dice sum of {state['currentDiceSum']} + {adds} adds = {total} Total Damage!"

    if net_spite > 0:
        msg += f" (Dealt {net_spite} direct Spite Damage!)"

    state['lastDamageMessage'] = msg


def finalize_round_history(state, str_lost=0):
    breakdown_parts = []
    for h in state['rollHistory']:
        if h.get('dice') is not None:
            breakdown_parts.append(f"{h['phase']}: [{', '.join(map(str, h['dice']))}] (={h['sum']})")
        else:
            breakdown_parts.append(h['phase'])

    breakdown_str = " ➔ ".join(breakdown_parts)
    net_spite = get_available_spite(state)

    state['historyLog'].append({
        'round': state['roundNum'],
        'dice_breakdown': breakdown_str,
        'dice_sum': state['currentDiceSum'],
        'fire_damage': state.get('currentFireDiceSum', 0),
        'stunning_blow': state.get('stunningBlowActive', False),
        'spite': net_spite,
        'adds': state['currentAdds'],
        'total_damage': state['finalDamageThisRound'],
        'str_lost': str_lost,
        'str_remaining': state['currentStr'],
        'adds_next': state['currentAdds']
    })


@app.route('/')
def index():
    state = get_state()
    state['availableSpite'] = get_available_spite(state)
    context_extras = {'state': state}
    return render_template('index.html', state=state, ctx=context_extras)


@app.route('/api/start_combat', methods=['POST'])
def start_combat():
    data = request.json
    state = get_state()

    char_level = int(data.get('level', 1))
    char_iq = int(data.get('iq', 12))
    max_str = int(data.get('max_str', 40))
    base_dice = int(data.get('base_weapon_dice', 7))
    min_str = int(data.get('min_str_req', 24))
    initial_adds = int(data.get('initial_adds', 55))
    already_berserk = bool(data.get('already_berserk', False))
    has_insane = bool(data.get('has_insane_strength', True))
    has_stunning = bool(data.get('has_stunning_blow', True))
    has_sunflame = bool(data.get('has_sunflame', True))

    state.update({
        'inCombat': True,
        'roundNum': 1,
        'level': char_level,
        'iq': char_iq,
        'maxStr': max_str,
        'currentStr': max_str,
        'baseWeaponDice': base_dice,
        'activeWeaponDice': base_dice,
        'expectedDice': base_dice,
        'minStrReq': min_str,
        'currentAdds': initial_adds,
        'berserkActive': already_berserk,
        'hasInsaneStrengthFeat': has_insane,
        'hasStunningBlowFeat': has_stunning,
        'hasSunflameFeat': has_sunflame,
        'insaneStrengthActive': False,
        'stunningBlowActive': False,
        'sunflameActivatedThisRound': False,
        'sunflameTotalSpent': 0,
        'sunflamePendingDice': 0,
        'sunflamePostCombatPhase': False,
        'sunflameActiveRoll': False,
        'sunflameBonusSpiteAvailable': 0,
        'spentSpiteThisRound': 0,
        'damageResolvedThisRound': False,
        'abilityActivatedThisRound': False,
        'minStrWarningTriggered': False,
        'currentDiceSum': 0,
        'currentFireDiceSum': 0,
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

    is_sunflame_roll = state.get('sunflameActiveRoll', False)
    is_initial_roll = not state['currentSetInfo'] and not is_sunflame_roll and len(state['rollHistory']) == 0

    if not state['currentSetInfo'] and not is_sunflame_roll:
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

    if is_sunflame_roll:
        state['currentFireDiceSum'] = state.get('currentFireDiceSum', 0) + roll_sum
        phase_name = f"🔥 Sunflame Fire Damage ({state['expectedDice']}d6)"
    elif state['currentSetInfo']:
        phase_name = f"Roll-Over for Sets of [{state['currentSetInfo']['val']}]s"
    else:
        phase_name = "Base Weapon Roll"

    state['rollHistory'].append({
        'phase': phase_name,
        'dice': dice,
        'sum': roll_sum,
        'spite': spite
    })

    # Sunflame rolls happen strictly AFTER all normal or Berserker combat damage is resolved
    if is_sunflame_roll:
        state['sunflameActiveRoll'] = False
        if spite > 0 and state.get('hasSunflameFeat', False):
            state['sunflameBonusSpiteAvailable'] = state.get('sunflameBonusSpiteAvailable', 0) + spite

        compute_and_save_final_damage(state)
        state['damageResolvedThisRound'] = True

        # If 1s were rolled inside the Sunflame pool, let her choose how many to spend for +1d6 each
        if state.get('sunflameBonusSpiteAvailable', 0) > 0 and get_available_spite(state) >= 1:
            state['sunflamePostCombatPhase'] = True
            state['activePhase'] = 'damage'
        elif state['berserkActive']:
            state['sunflamePostCombatPhase'] = False
            state['activePhase'] = 'str_loss'
        else:
            state['sunflamePostCombatPhase'] = False
            state['activePhase'] = 'results'

        save_state(state)
        return jsonify({
            'status': 'damage_done',
            'final_total': state['finalDamageThisRound'],
            'message': state['lastDamageMessage'],
            'state': state
        })

    # Standard Weapon Roll or Berserk Set Roll-Over
    if state['currentSetInfo']:
        state['currentSetInfo'] = None

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

    available_spite = get_available_spite(state)
    can_afford_berserk = (not state['berserkActive']) and (available_spite >= 2)
    can_afford_insane = state['hasInsaneStrengthFeat'] and (state['insaneStrengthActive'] or available_spite >= 3)
    can_afford_stunning = state.get('hasStunningBlowFeat', False) and (state.get('stunningBlowActive', False) or available_spite >= 2)
    can_select_sunflame = state.get('hasSunflameFeat', False) and (
        state.get('sunflameActivatedThisRound', False) or available_spite >= 3
    )

    if state['berserkActive']:
        if state['pendingSets'] or state['currentSetInfo'] or can_afford_insane or can_afford_stunning or can_select_sunflame:
            state['activePhase'] = 'damage'
        else:
            state['activePhase'] = 'str_loss'
    else:
        if can_afford_berserk or can_afford_insane or can_afford_stunning or can_select_sunflame:
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
        state['berserkActive'] = False
        state['spentSpiteThisRound'] -= 2
        state['pendingSets'] = []
        state['currentSetInfo'] = None
    else:
        if get_available_spite(state) < 2:
            return jsonify({'status': 'error', 'message': 'Not enough Spite.'}), 400
        state['berserkActive'] = True
        state['spentSpiteThisRound'] += 2
        state['abilityActivatedThisRound'] = True

        recalculated_sets = []
        for h in state['rollHistory']:
            dice = h.get('dice')
            if dice and "Sunflame Fire Damage" not in h.get('phase', ''):
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
        if get_available_spite(state) < 3:
            return jsonify({'status': 'error', 'message': 'Not enough Spite.'}), 400
        state['insaneStrengthActive'] = True
        state['abilityActivatedThisRound'] = True

    compute_and_save_final_damage(state)
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/toggle_stunning_blow', methods=['POST'])
def toggle_stunning_blow():
    state = get_state()
    if state.get('stunningBlowActive', False):
        state['stunningBlowActive'] = False
    else:
        if get_available_spite(state) < 2:
            return jsonify({'status': 'error', 'message': 'Not enough Spite.'}), 400
        state['stunningBlowActive'] = True
        state['abilityActivatedThisRound'] = True

    compute_and_save_final_damage(state)
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/toggle_sunflame', methods=['POST'])
def toggle_sunflame():
    state = get_state()
    if state.get('sunflameActivatedThisRound', False):
        if not state.get('sunflamePostCombatPhase', False):
            state['sunflameActivatedThisRound'] = False
            state['sunflameTotalSpent'] = 0
            state['sunflamePendingDice'] = 0
            state['rollHistory'] = [
                h for h in state['rollHistory']
                if not (h.get('dice') is None and "Activated Sunflame" in h.get('phase', ''))
            ]
    else:
        if get_available_spite(state) < 3:
            return jsonify({'status': 'error', 'message': 'Need at least 3 available Spite to select Sunflame.'}), 400
        state['sunflameActivatedThisRound'] = True
        state['sunflameTotalSpent'] = 3
        state['sunflamePendingDice'] = 3
        state['abilityActivatedThisRound'] = True

    compute_and_save_final_damage(state)
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/add_sunflame_spite', methods=['POST'])
def add_sunflame_spite():
    state = get_state()
    if not state.get('sunflamePostCombatPhase', False):
        return jsonify({'status': 'error', 'message': 'Finish normal/Berserker combat first before adding Sunflame Spite.'}), 400
    if not state.get('sunflameActivatedThisRound', False):
        return jsonify({'status': 'error', 'message': 'Sunflame is not active this round.'}), 400

    data = request.json or {}
    amount = int(data.get('amount', 1))
    available = get_available_spite(state)
    is_bonus_phase = state.get('sunflameBonusSpiteAvailable', 0) > 0
    max_allowed = min(available, state['sunflameBonusSpiteAvailable']) if is_bonus_phase else available

    if amount < 1 or amount > max_allowed:
        return jsonify({'status': 'error', 'message': f'Must spend between 1 and {max_allowed} Spite.'}), 400

    state['sunflameTotalSpent'] = state.get('sunflameTotalSpent', 0) + amount
    state['sunflamePendingDice'] = state.get('sunflamePendingDice', 0) + amount
    state['abilityActivatedThisRound'] = True

    if is_bonus_phase:
        state['sunflameBonusSpiteAvailable'] = max(0, state['sunflameBonusSpiteAvailable'] - amount)

    state['rollHistory'].append({
        'phase': f"🔥 Fed Sunflame (+{amount} Spite for +{amount}d6 Fire)",
        'dice': None,
        'sum': 0,
        'spite': 0
    })

    compute_and_save_final_damage(state)
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/cancel_sunflame_pending', methods=['POST'])
def cancel_sunflame_pending():
    state = get_state()
    pending = state.get('sunflamePendingDice', 0)
    has_rolled_sunflame = any(
        h.get('dice') is not None and "Sunflame Fire Damage" in h.get('phase', '')
        for h in state['rollHistory']
    )
    if not has_rolled_sunflame:
        extra = max(0, pending - 3)
        if extra > 0:
            state['sunflameTotalSpent'] = max(3, state.get('sunflameTotalSpent', 3) - extra)
            state['sunflamePendingDice'] = 3
            state['rollHistory'] = [
                h for h in state['rollHistory']
                if not (h.get('dice') is None and "Fed Sunflame" in h.get('phase', ''))
            ]
    elif pending > 0:
        state['sunflameTotalSpent'] = max(0, state.get('sunflameTotalSpent', 0) - pending)
        state['sunflamePendingDice'] = 0
        state['rollHistory'] = [
            h for h in state['rollHistory']
            if not (h.get('dice') is None and "Fed Sunflame" in h.get('phase', ''))
        ]

    compute_and_save_final_damage(state)
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/advance_after_ability', methods=['POST'])
def advance_after_ability():
    state = get_state()
    state['abilityActivatedThisRound'] = False
    state['sunflameBonusSpiteAvailable'] = 0

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

    if state.get('stunningBlowActive', False):
        already_logged = any("Stunning Blow" in h.get('phase', '') for h in state['rollHistory'])
        if not already_logged:
            state['rollHistory'].append({
                'phase': "💫 Activated Stunning Blow (Spent 2 Spite: Target loses ½ HPT)",
                'dice': None,
                'sum': 0,
                'spite': 0
            })

    if state.get('sunflameActivatedThisRound', False):
        already_logged = any("Activated Sunflame" in h.get('phase', '') for h in state['rollHistory'])
        if not already_logged:
            state['rollHistory'].append({
                'phase': "🔥 Activated Sunflame (Spent 3 Spite for +3d6 Fire)",
                'dice': None,
                'sum': 0,
                'spite': 0
            })

    # 1. Always finish Berserker rollover sets first
    if state['berserkActive'] and state['pendingSets']:
        next_set = state['pendingSets'].pop(0)
        state['currentSetInfo'] = next_set
        state['expectedDice'] = next_set['count']
        state['activePhase'] = 'damage'
    # 2. Enter Sunflame post-combat phase so she can add extra Spite (if she has any) or roll immediately
    elif state.get('sunflameActivatedThisRound', False) and not state.get('sunflamePostCombatPhase', False):
        state['sunflamePostCombatPhase'] = True
        if get_available_spite(state) >= 1:
            state['activePhase'] = 'damage'
        else:
            state['expectedDice'] = state['sunflamePendingDice']
            state['sunflamePendingDice'] = 0
            state['sunflameActiveRoll'] = True
            state['activePhase'] = 'damage'
    # 3. Roll queued Sunflame fire dice
    elif state.get('sunflamePendingDice', 0) > 0:
        state['expectedDice'] = state['sunflamePendingDice']
        state['sunflamePendingDice'] = 0
        state['sunflameActiveRoll'] = True
        state['activePhase'] = 'damage'
    # 4. Done with Sunflame & Combat Damage -> proceed to STR loss or Results
    elif state['berserkActive']:
        state['sunflamePostCombatPhase'] = False
        state['activePhase'] = 'str_loss'
    else:
        state['sunflamePostCombatPhase'] = False
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

    state['lastStrLost'] = str_lost

    warning_msg = None
    if new_str < state['minStrReq']:
        if not state['minStrWarningTriggered']:
            warning_msg = f"⚠️ WARNING: Your Strength ({new_str}) fell below weapon minimum requirement ({state['minStrReq']})! Please adjust your dice pool if needed."
            state['minStrWarningTriggered'] = True
    else:
        state['minStrWarningTriggered'] = False

    if new_str <= 0:
        finalize_round_history(state, str_lost=str_lost)
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


@app.route('/api/adjust_iq', methods=['POST'])
def adjust_iq():
    state = get_state()
    data = request.json or {}
    delta = int(data.get('delta', 0))
    state['iq'] = max(1, state.get('iq', 12) + delta)
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


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
    state['stunningBlowActive'] = False
    state['sunflameActivatedThisRound'] = False
    state['sunflameTotalSpent'] = 0
    state['sunflamePendingDice'] = 0
    state['sunflamePostCombatPhase'] = False
    state['sunflameActiveRoll'] = False
    state['sunflameBonusSpiteAvailable'] = 0
    state['spentSpiteThisRound'] = 0
    state['damageResolvedThisRound'] = False
    state['abilityActivatedThisRound'] = False
    state['lastDamageMessage'] = ""
    state['expectedDice'] = state['activeWeaponDice']
    state['currentDiceSum'] = 0
    state['currentFireDiceSum'] = 0
    state['currentSpiteTotal'] = 0
    state['finalDamageThisRound'] = 0
    state['pendingSets'] = []
    state['currentSetInfo'] = None
    state['rollHistory'] = []
    state['activePhase'] = 'damage'
    save_state(state)
    return jsonify({'status': 'ok', 'state': state})


@app.route('/api/stunt_stop_berserk', methods=['POST'])
def stunt_stop_berserk():
    state = get_state()
    state['berserkActive'] = False

    state['rollHistory'].append({
        'phase': "🤝 Helping Stunt Calmed Berserker! (Exited Berserk)",
        'dice': None,
        'sum': 0,
        'spite': 0
    })

    save_state(state)
    return jsonify({
        'status': 'ok',
        'message': "🤝 A helping stunt successfully snapped you out of your rage! You have exited Berserk mode.",
        'state': state
    })


@app.route('/api/next_round', methods=['POST'])
def next_round():
    state = get_state()
    data = request.json or {}

    stop_requested = data.get('stopped', False)
    iq_status = data.get('iq_status')

    if iq_status == 'passed':
        state['rollHistory'].append({
            'phase': f"🧠 Passed Level {state.get('level', 1)} IQ Saving Roll",
            'dice': None,
            'sum': 0,
            'spite': 0
        })
    elif iq_status == 'failed':
        state['rollHistory'].append({
            'phase': f"🧠 Failed Level {state.get('level', 1)} IQ Saving Roll",
            'dice': None,
            'sum': 0,
            'spite': 0
        })

    str_lost = state.pop('lastStrLost', 0)
    finalize_round_history(state, str_lost=str_lost)

    state['roundNum'] += 1
    state['insaneStrengthActive'] = False
    state['stunningBlowActive'] = False
    state['sunflameActivatedThisRound'] = False
    state['sunflameTotalSpent'] = 0
    state['sunflamePendingDice'] = 0
    state['sunflamePostCombatPhase'] = False
    state['sunflameActiveRoll'] = False
    state['sunflameBonusSpiteAvailable'] = 0
    state['spentSpiteThisRound'] = 0
    state['damageResolvedThisRound'] = False
    state['abilityActivatedThisRound'] = False
    state['lastDamageMessage'] = ""
    state['expectedDice'] = state['activeWeaponDice']
    state['currentDiceSum'] = 0
    state['currentFireDiceSum'] = 0
    state['currentSpiteTotal'] = 0
    state['finalDamageThisRound'] = 0
    state['pendingSets'] = []
    state['currentSetInfo'] = None
    state['rollHistory'] = []
    state['activePhase'] = 'damage'

    if stop_requested:
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
        'Fire Damage',
        'Stunning Blow Active',
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
            row.get('fire_damage', 0),
            'Yes' if row.get('stunning_blow') else 'No',
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