from flask import Flask, render_template, request, jsonify, session
import random

app = Flask(__name__)
app.secret_key = 'berserker_secret_key_monsters_monsters'

def parse_dice(dice_str):
    try:
        return [int(x.strip()) for x in dice_str.replace(',', ' ').split() if x.strip() and x.strip().isdigit()]
    except ValueError:
        return []

def analyze_roll(dice):
    """Finds matching sets and returns details on which dice exploded."""
    if len(dice) < 2:
        return {}, 0, []
    
    counts = {}
    for die in dice:
        counts[die] = counts.get(die, 0) + 1
        
    matching_sets = {val: count for val, count in counts.items() if count >= 2}
    total_extra_dice = sum(matching_sets.values())
    
    matching_values = []
    for val, count in matching_sets.items():
        matching_values.extend([val] * count)
        
    return matching_sets, total_extra_dice, sorted(matching_values)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/start', methods=['POST'])
def start_combat():
    data = request.json
    max_str = int(data.get('max_str', 18))
    weapon_dice = int(data.get('weapon_dice', 3))
    initial_adds = int(data.get('initial_adds', 0))
    
    session['max_str'] = max_str
    session['current_str'] = max_str
    session['weapon_dice'] = weapon_dice
    session['initial_adds'] = initial_adds
    session['current_adds'] = initial_adds
    
    session['round_num'] = 1
    session['history'] = []
    session['roll_history_this_round'] = []
    session['current_dice_sum'] = 0
    session['phase_count'] = 1
    
    return jsonify({
        'status': 'success',
        'current_str': max_str,
        'max_str': max_str,
        'weapon_dice': weapon_dice,
        'current_adds': initial_adds,
        'round_num': 1
    })

@app.route('/api/roll_damage', methods=['POST'])
def roll_damage():
    data = request.json
    auto_roll = data.get('auto_roll', False)
    dice_input = data.get('dice_input', '')
    
    # Determine expected dice count
    if session['phase_count'] == 1:
        expected_dice = session.get('weapon_dice', 3)
    else:
        expected_dice = session.get('pending_extra_dice', 0)
    
    if auto_roll:
        dice = [random.randint(1, 6) for _ in range(expected_dice)]
    else:
        dice = parse_dice(dice_input)
        
    if len(dice) != expected_dice:
        return jsonify({
            'status': 'error', 
            'message': f'⚠️ Incorrect number of dice! You must enter exactly {expected_dice} dice values.'
        }), 400

    dice_sum = sum(dice)
    session['current_dice_sum'] += dice_sum
    
    matching_sets, total_extra_dice, matching_values = analyze_roll(dice)
    
    # Record phase history
    phase_label = "Initial Roll" if session['phase_count'] == 1 else f"Roll-Over #{session['phase_count'] - 1}"
    session['roll_history_this_round'].append({
        'phase': phase_label,
        'dice': dice,
        'sum': dice_sum
    })
    
    if total_extra_dice > 0:
        session['phase_count'] += 1
        session['pending_extra_dice'] = total_extra_dice
        
        set_descriptions = []
        for val, c in matching_sets.items():
            name = "Doubles" if c == 2 else "Triples" if c == 3 else f"{c}-of-a-kind"
            set_descriptions.append(f"{name} of [{val}]s ({c} dice)")
            
        action_instruction = (
            f" Pick up the {total_extra_dice} matching dice that rolled {matching_values}. "
            f"Roll those exact {total_extra_dice} dice again and enter their new values below."
        )
        
        return jsonify({
            'status': 'rollover',
            'rolled_dice': dice,
            'current_dice_sum': session['current_dice_sum'],
            'matching_sets': set_descriptions,
            'matching_values': matching_values,
            'pending_extra_dice': total_extra_dice,
            'action_instruction': action_instruction,
            'roll_history': session['roll_history_this_round'],
            'message': f"🔥 BERSERK EXPLOSION DETECTED! You rolled: {', '.join(set_descriptions)}."
        })
    else:
        adds = session.get('current_adds', 0)
        final_total = session['current_dice_sum'] + adds
        session['final_round_damage'] = final_total
        
        return jsonify({
            'status': 'damage_done',
            'rolled_dice': dice,
            'dice_damage': session['current_dice_sum'],
            'current_adds': adds,
            'total_damage': final_total,
            'roll_history': session['roll_history_this_round'],
            'message': f"✅ All damage dice resolved! Total Dice Sum: {session['current_dice_sum']} + Adds (+{adds}) = {final_total} Total Damage."
        })

@app.route('/api/roll_str_loss', methods=['POST'])
def roll_str_loss():
    data = request.json
    auto_roll = data.get('auto_roll', False)
    loss_val = data.get('loss_val', None)
    
    if auto_roll:
        str_lost = random.randint(1, 6)
    else:
        try:
            str_lost = int(loss_val)
        except (ValueError, TypeError):
            return jsonify({'status': 'error', 'message': 'Please enter a valid number from 1 to 6.'}), 400

    session['current_str'] -= str_lost
    curr_str = max(0, session['current_str'])
    max_str = session['max_str']
    
    session['current_adds'] = max(0, session['current_adds'] - str_lost)
    curr_adds = session['current_adds']
    
    round_num = session['round_num']
    total_damage = session.get('final_round_damage', 0)
    dice_sum = session.get('current_dice_sum', 0)
    
    # Format roll history string for table
    rolls_summary = " ➔ ".join([f"{r['phase']}: {r['dice']} (={r['sum']})" for r in session['roll_history_this_round']])
    
    log_entry = {
        'round': round_num,
        'dice_breakdown': rolls_summary,
        'dice_sum': dice_sum,
        'adds': session['initial_adds'] if round_num == 1 else session['history'][-1]['adds_next'],
        'total_damage': total_damage,
        'str_lost': str_lost,
        'str_remaining': curr_str,
        'adds_next': curr_adds
    }
    session['history'].append(log_entry)
    session.modified = True

    if curr_str <= 0:
        session['stage'] = 'UNCONSCIOUS'
        return jsonify({
            'status': 'unconscious',
            'str_lost': str_lost,
            'current_str': 0,
            'current_adds': 0,
            'history': session['history'],
            'rest_turns_needed': max_str,
            'message': "💥 YOU FELL UNCONSCIOUS! Berserking ends immediately."
        })
    else:
        session['stage'] = 'ROUND_END'
        return jsonify({
            'status': 'next_round_prompt',
            'str_lost': str_lost,
            'current_str': curr_str,
            'current_adds': curr_adds,
            'history': session['history'],
            'message': f"📉 Lost {str_lost} STR. STR remaining: {curr_str}/{max_str}. Updated Adds: {curr_adds}."
        })

@app.route('/api/next_round', methods=['POST'])
def next_round():
    data = request.json
    stopped = data.get('stopped', False)
    
    if stopped:
        curr_str = session['current_str']
        max_str = session['max_str']
        turns_needed = max_str - curr_str
        return jsonify({
            'status': 'stopped',
            'rest_turns_needed': turns_needed,
            'message': "✨ You snapped out of the berserk rage!"
        })

    session['round_num'] += 1
    session['current_dice_sum'] = 0
    session['roll_history_this_round'] = []
    session['phase_count'] = 1
    session['stage'] = 'INITIAL_DAMAGE'
    
    return jsonify({
        'status': 'continue',
        'round_num': session['round_num'],
        'current_str': session['current_str'],
        'current_adds': session['current_adds']
    })

if __name__ == '__main__':
    app.run(debug=True)