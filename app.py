from flask import Flask, render_template, request, jsonify
import random

app = Flask(__name__)

def parse_dice(dice_str):
    try:
        return [int(x.strip()) for x in dice_str.replace(',', ' ').split() if x.strip() and x.strip().isdigit()]
    except ValueError:
        return []

def analyze_roll(dice):
    if len(dice) < 2:
        return []
    
    counts = {}
    for die in dice:
        counts[die] = counts.get(die, 0) + 1
        
    exploding_sets = []
    for val, count in sorted(counts.items()):
        if count >= 2:
            set_type = "Doubles" if count == 2 else "Triples" if count == 3 else f"{count}-of-a-kind"
            exploding_sets.append({
                'value': val,
                'count': count,
                'description': f"{set_type} of [{val}]s"
            })
            
    return exploding_sets

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/roll_damage', methods=['POST'])
def roll_damage():
    data = request.json or {}
    auto_roll = data.get('auto_roll', False)
    dice_input = data.get('dice_input', '')
    expected_dice = int(data.get('expected_dice', 3))
    current_dice_sum = int(data.get('current_dice_sum', 0))
    current_spite_total = int(data.get('current_spite_total', 0))
    spent_spite = int(data.get('spent_spite', 0))
    berserk_active = data.get('berserk_active', False)
    roll_history = data.get('roll_history', [])
    current_adds = int(data.get('current_adds', 0))
    pending_sets = data.get('pending_sets', [])
    current_set_info = data.get('current_set_info', None)
    
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
    new_dice_sum = current_dice_sum + dice_sum
    
    phase_spite = dice.count(1)
    new_spite_total = current_spite_total + phase_spite
    
    # Deduct spent spite from available pool
    available_spite_for_feats = max(0, new_spite_total - spent_spite)
    spite_triggered = available_spite_for_feats >= 3
    
    # STRICT CHECK: NEVER offer to spend spite if Berserk is already active OR spite was already spent
    can_spend_for_berserk = (available_spite_for_feats >= 2) and (not berserk_active) and (spent_spite == 0)
    
    if current_set_info:
        phase_label = f"Roll-Over for {current_set_info['description']}"
    else:
        phase_label = "Base Weapon Roll"

    roll_history.append({
        'phase': phase_label,
        'dice': dice,
        'sum': dice_sum,
        'spite': phase_spite
    })
    
    new_exploding_sets = analyze_roll(dice)
    all_pending_sets = pending_sets + new_exploding_sets
    
    if len(all_pending_sets) > 0:
        next_set = all_pending_sets.pop(0)
        action_instruction = (
            f" Pick up the {next_set['count']} dice that rolled [{next_set['value']}]. "
            f"Roll those exact {next_set['count']} dice for your {next_set['description']} and enter their new values below."
        )
        
        return jsonify({
            'status': 'rollover',
            'rolled_dice': dice,
            'current_dice_sum': new_dice_sum,
            'current_spite_total': new_spite_total,
            'available_spite_for_feats': available_spite_for_feats,
            'can_spend_for_berserk': can_spend_for_berserk,
            'pending_sets': all_pending_sets,
            'current_set_info': next_set,
            'expected_dice': next_set['count'],
            'action_instruction': action_instruction,
            'roll_history': roll_history,
            'spite_triggered': spite_triggered,
            'message': f"🔥 BERSERK EXPLOSION! Resolving {next_set['description']} ({next_set['count']} dice)."
        })
    else:
        final_total = new_dice_sum + current_adds
        return jsonify({
            'status': 'damage_done',
            'rolled_dice': dice,
            'current_dice_sum': new_dice_sum,
            'current_spite_total': new_spite_total,
            'available_spite_for_feats': available_spite_for_feats,
            'can_spend_for_berserk': can_spend_for_berserk,
            'final_total': final_total,
            'roll_history': roll_history,
            'spite_triggered': spite_triggered,
            'message': f"✅ Damage resolved! Dice Sum: {new_dice_sum} + Adds (+{current_adds}) = {final_total} Total Damage. 🎯 Spite Damage Dealt: {new_spite_total}."
        })

@app.route('/api/roll_str_loss', methods=['POST'])
def roll_str_loss():
    data = request.json or {}
    auto_roll = data.get('auto_roll', False)
    loss_val = data.get('loss_val', None)
    
    current_str = int(data.get('current_str', 18))
    max_str = int(data.get('max_str', 18))
    current_adds = int(data.get('current_adds', 0))
    min_str_req = int(data.get('min_str_req', 15))
    base_weapon_dice = int(data.get('base_weapon_dice', 8))
    round_num = int(data.get('round_num', 1))
    final_damage = int(data.get('final_damage', 0))
    dice_sum = int(data.get('dice_sum', 0))
    spite_total = int(data.get('spite_total', 0))
    spent_spite = int(data.get('spent_spite', 0))
    roll_history = data.get('roll_history', [])
    history_log = data.get('history_log', [])
    insane_strength_active = data.get('insane_strength_active', False)

    if auto_roll:
        str_lost = random.randint(1, 6)
    else:
        try:
            str_lost = int(loss_val)
        except (ValueError, TypeError):
            return jsonify({'status': 'error', 'message': 'Please enter a valid number from 1 to 6.'}), 400

    new_str = max(0, current_str - str_lost)
    new_adds = max(0, current_adds - str_lost)
    
    if new_str < min_str_req:
        str_deficit = min_str_req - new_str
        dice_penalty = (str_deficit + 1) // 2
        effective_dice = max(1, base_weapon_dice - dice_penalty)
        warning_msg = f"⚠️ STR dropped to {new_str} (below required {min_str_req})! Next round weapon dice reduced to {effective_dice}d6."
    else:
        effective_dice = base_weapon_dice
        warning_msg = None

    rolls_summary = " ➔ ".join([f"{r['phase']}: {r['dice']} (={r['sum']})" for r in roll_history])
    if spent_spite > 0:
        rolls_summary += f" [🔥 Spent {spent_spite} Spite to Activate Berserk]"
    if insane_strength_active:
        rolls_summary += " [💪 INSANE STRENGTH ACTIVE]"

    log_entry = {
        'round': round_num,
        'dice_breakdown': rolls_summary,
        'dice_sum': dice_sum,
        'spite': spite_total,
        'adds': current_adds,
        'total_damage': final_damage,
        'str_lost': str_lost,
        'str_remaining': new_str,
        'adds_next': new_adds
    }
    history_log.append(log_entry)

    is_unconscious = new_str <= 0

    return jsonify({
        'status': 'unconscious' if is_unconscious else 'next_round_prompt',
        'str_lost': str_lost,
        'new_str': new_str,
        'new_adds': new_adds,
        'effective_dice': effective_dice,
        'warning_msg': warning_msg,
        'history_log': history_log,
        'rest_turns_needed': max_str - new_str,
        'message': "💥 YOU FELL UNCONSCIOUS! Berserking ends immediately." if is_unconscious else f"📉 Lost {str_lost} STR. Base STR remaining: {new_str}/{max_str}. Updated Adds: {new_adds}."
    })

if __name__ == '__main__':
    app.run(debug=True)