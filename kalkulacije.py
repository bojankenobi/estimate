# -*- coding: utf-8 -*-
import streamlit as st
import sqlite3
import os
import math
import pandas as pd
import datetime
import io
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT

# --- PRVA Streamlit komanda ---
st.set_page_config(page_title="Print Calculation", layout="wide")

# --- Konstante i podrazumevane vrednosti ---
PITCH = 3.175; GAP_MIN = 2.5; GAP_MAX = 4.0; Z_MIN = 70; Z_MAX = 140
TOTAL_CYLINDER_WIDTH = 200; WORKING_WIDTH = 190; WIDTH_GAP = 5
WIDTH_WASTE = 10; MAX_MATERIAL_WIDTH = 200
BASE_WASTE_LENGTH = 50.0; WASTE_LENGTH_PER_COLOR = 50.0
SETUP_TIME_PER_COLOR_OR_BASE = 30; CLEANUP_TIME_MIN = 30
MACHINE_SPEED_MIN = 10; MACHINE_SPEED_MAX = 120
GRAMS_INK_PER_M2 = 3.0; GRAMS_VARNISH_PER_M2 = 4.0

FALLBACK_INK_PRICE = 2350.0
FALLBACK_VARNISH_PRICE = 1800.0
FALLBACK_LABOR_PRICE = 3000.0
FALLBACK_TOOL_SEMI_PRICE = 6000.0
FALLBACK_TOOL_ROT_PRICE = 8000.0
FALLBACK_PLATE_PRICE = 2000.0
FALLBACK_SINGLE_PROFIT = 0.25 # Fallback za pojedinačnu kalkulaciju
FALLBACK_MACHINE_SPEED = 30

FALLBACK_PROFITS = { 1000: 0.30, 10000: 0.25, 20000: 0.22, 50000: 0.20, 100000: 0.18 }
QUANTITIES_FOR_OFFER = list(FALLBACK_PROFITS.keys())

DB_FILE = "print_calculator.db"

# Nema više TECHNOLOGY_CODES

# --- Funkcije za rad sa bazom podataka (OČIŠĆENE od print/st.write za greške) ---
def get_db_connection():
    """Uspostavlja konekciju sa SQLite bazom. Vraća konekciju ili None."""
    try:
        conn = sqlite3.connect(DB_FILE, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        # Nema print-a ovde
        return None

def init_db():
    """Inicijalizuje bazu podataka. Vraća True ako uspe, False ako ne."""
    conn = get_db_connection();
    if conn is None: return False
    success = False
    try:
        cursor = conn.cursor()
        cursor.execute(""" CREATE TABLE IF NOT EXISTS materials ( id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, price_per_m2 REAL NOT NULL ) """)
        cursor.execute(""" CREATE TABLE IF NOT EXISTS settings ( key TEXT PRIMARY KEY NOT NULL, value REAL NOT NULL ) """)
        cursor.execute(""" CREATE TABLE IF NOT EXISTS calculations ( id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, client_name TEXT, product_name TEXT, template_width REAL, template_height REAL, quantity INTEGER, num_colors INTEGER, is_blank BOOLEAN, is_uv_varnish BOOLEAN, material_name TEXT, tool_type TEXT, machine_speed REAL, profit_coefficient REAL, calculated_total_price REAL, calculated_price_per_piece REAL ) """)
        # Nema ALTER TABLE jer je ovo verzija bez technology_code
        cursor.execute("SELECT COUNT(*) FROM materials")
        if cursor.fetchone()[0] == 0: default_materials = {"Paper (chrome)": 39.95, "Plastic (PPW)": 54.05, "Thermal Paper": 49.35}; [cursor.execute("INSERT INTO materials (name, price_per_m2) VALUES (?, ?)", (name, price)) for name, price in default_materials.items()]
        default_settings = { "ink_price_per_kg": FALLBACK_INK_PRICE, "varnish_price_per_kg": FALLBACK_VARNISH_PRICE, "machine_labor_price_per_hour": FALLBACK_LABOR_PRICE, "tool_price_semirotary": FALLBACK_TOOL_SEMI_PRICE, "tool_price_rotary": FALLBACK_TOOL_ROT_PRICE, "plate_price_per_color": FALLBACK_PLATE_PRICE, "machine_speed_default": FALLBACK_MACHINE_SPEED, "single_calc_profit_coefficient": FALLBACK_SINGLE_PROFIT }; [default_settings.update({f"profit_coeff_{qty}": coeff}) for qty, coeff in FALLBACK_PROFITS.items()]
        [cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value)) for key, value in default_settings.items()]
        conn.commit()
        success = True
    except sqlite3.Error as e:
        # Nema print-a ovde
        success = False # Samo postavi status neuspeha
    finally:
        if conn: conn.close()
    return success

def load_materials_from_db():
    """Učitava materijale. Vraća rečnik ili None ako ne uspe."""
    materials = None; conn = get_db_connection();
    if conn is None: return None
    try: cursor = conn.cursor(); cursor.execute("SELECT name, price_per_m2 FROM materials ORDER BY name"); materials = {row['name']: row['price_per_m2'] for row in cursor.fetchall()}
    except sqlite3.Error as e: materials = None # Greška, vrati None
    finally:
        if conn: conn.close()
    return materials

def load_settings_from_db():
    """Učitava podešavanja. Vraća rečnik ili None ako ne uspe."""
    settings = None; conn = get_db_connection();
    if conn is None: return None
    try: cursor = conn.cursor(); cursor.execute("SELECT key, value FROM settings"); settings = {row['key']: row['value'] for row in cursor.fetchall()}
    except sqlite3.Error as e: settings = None # Greška, vrati None
    finally:
        if conn: conn.close()
    return settings

def update_material_price_in_db(name, price):
    """Vraća True ako uspe, False ako ne."""
    conn = get_db_connection();
    if conn is None: return False; success = False
    try: cursor = conn.cursor(); cursor.execute("UPDATE materials SET price_per_m2 = ? WHERE name = ?", (price, name)); conn.commit(); success = True
    except sqlite3.Error as e: success = False
    finally:
        if conn: conn.close()
    return success

def update_setting_in_db(key, value):
    """Vraća True ako uspe, False ako ne."""
    conn = get_db_connection();
    if conn is None: return False; success = False
    try: cursor = conn.cursor(); cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)); conn.commit(); success = True
    except sqlite3.Error as e: success = False
    finally:
        if conn: conn.close()
    return success

# Ažurirano: Funkcija za čuvanje BEZ technology_code
def save_calculation_to_db(calc_data):
    """Vraća True ako uspe, False ako ne."""
    conn = get_db_connection();
    if conn is None: return False; success = False
    sql = """INSERT INTO calculations (client_name, product_name, template_width, template_height, quantity, num_colors, is_blank, is_uv_varnish, material_name, tool_type, machine_speed, profit_coefficient, calculated_total_price, calculated_price_per_piece) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
    profit_coeff_to_save = calc_data.get('profit_coefficient_used'); params = (calc_data.get('client_name'), calc_data.get('product_name'), calc_data.get('template_width_W_input'), calc_data.get('template_height_H_input'), calc_data.get('quantity_input'), calc_data.get('valid_num_colors_for_calc'), calc_data.get('is_blank'), calc_data.get('is_uv_varnish_input'), calc_data.get('selected_material'), calc_data.get('tool_info_string'), calc_data.get('machine_speed_m_min'), profit_coeff_to_save, calc_data.get('total_selling_price_rsd'), calc_data.get('selling_price_per_piece_rsd'))
    try: cursor = conn.cursor(); cursor.execute(sql, params); conn.commit(); success = True
    except sqlite3.Error as e: st.error(f"Error saving calculation to DB: {e}") # Ovde MOŽEMO prikazati grešku jer je to akcija korisnika
    finally:
        if conn: conn.close()
    return success

# --- Calculation Functions ---
def find_cylinder_specifications(template_width_W):
    valid_solutions = []; message = "";
    if template_width_W <= 0: return None, [], "Error: Template width must be > 0."
    for z in range(Z_MIN, Z_MAX + 1):
        circumference_C = z * PITCH;
        if (template_width_W + GAP_MIN) <= 1e-9: continue
        n_max_possible = math.floor(circumference_C / (template_width_W + GAP_MIN))
        for n in range(1, n_max_possible + 1):
            if n == 0: continue
            gap_G_circumference = (circumference_C / n) - template_width_W; tolerance = 1e-9
            if (GAP_MIN - tolerance) <= gap_G_circumference <= (GAP_MAX + tolerance): valid_solutions.append({"number_of_teeth_Z": z, "circumference_mm": circumference_C, "templates_N_circumference": n, "gap_G_circumference_mm": gap_G_circumference})
    if not valid_solutions: message = f"No cylinder found ({Z_MIN}-{Z_MAX} teeth) for W={template_width_W:.3f}mm with G={GAP_MIN:.1f}-{GAP_MAX:.1f}mm."; return None, [], message
    valid_solutions.sort(key=lambda x: (x["number_of_teeth_Z"], -x["templates_N_circumference"]))
    return valid_solutions[0], valid_solutions, "Circumference calculation OK."

def calculate_number_across_width(template_height_H, working_width, width_gap):
    if template_height_H <= 0: return 0;
    if template_height_H > working_width: return 0
    if template_height_H <= working_width and (template_height_H * 2 + width_gap) > working_width: return 1
    denominator = template_height_H + width_gap;
    if denominator <= 1e-9: return 0
    return int(math.floor((working_width + width_gap) / denominator))

def calculate_material_width(number_across_width_y, template_height_H, width_gap, width_waste):
    if number_across_width_y <= 0: return 0
    total_template_width = number_across_width_y * template_height_H; total_gap_width = max(0, number_across_width_y - 1) * width_gap
    return total_template_width + total_gap_width + width_waste

def format_time(total_minutes):
    if total_minutes < 0: return "N/A"; total_minutes = round(total_minutes);
    if total_minutes == 0: return "0 min";
    if total_minutes < 60: return f"{total_minutes} min"
    hours, minutes = divmod(total_minutes, 60); hours = int(hours); minutes = int(minutes)
    if minutes == 0: return f"{hours} h"; return f"{hours} h {minutes} min"

# --- Funkcija za jednu kalkulaciju (AŽURIRANA: Uklonjen technology_code) ---
def run_single_calculation( quantity: int, template_width_W: float, template_height_H: float, best_circumference_solution: dict, number_across_width_y: int, is_blank: bool, num_colors: int, is_uv_varnish: bool, price_per_m2: float, machine_speed_m_min: float, selected_tool_key: str, existing_tool_info: str, profit_coefficient: float, ink_price_kg: float, varnish_price_kg: float, plate_price_color: float, labor_price_hour: float, tool_price_semi: float, tool_price_rot: float ) -> dict: # Nema technology_code
    results = {};
    if not best_circumference_solution or number_across_width_y <= 0: results['error'] = "Invalid cylinder/width."; results['total_selling_price_rsd'] = 0.0; results['selling_price_per_piece_rsd'] = 0.0; return results
    gap_G_circumference_mm = best_circumference_solution['gap_G_circumference_mm']; required_material_width_mm = calculate_material_width(number_across_width_y, template_height_H, WIDTH_GAP, WIDTH_WASTE); results['required_material_width_mm'] = required_material_width_mm; results['material_width_exceeded'] = required_material_width_mm > MAX_MATERIAL_WIDTH; total_production_length_m = 0.0; total_production_area_m2 = 0.0
    if number_across_width_y > 0: segment_length_mm = template_width_W + gap_G_circumference_mm; total_production_length_m = (quantity / number_across_width_y) * segment_length_mm / 1000;
    if required_material_width_mm > 0: total_production_area_m2 = total_production_length_m * (required_material_width_mm / 1000)
    results['total_production_length_m'] = total_production_length_m; results['total_production_area_m2'] = total_production_area_m2; num_colors_for_waste_time = 1 if is_blank else num_colors; waste_length_m = BASE_WASTE_LENGTH + (0 if is_blank else (num_colors * WASTE_LENGTH_PER_COLOR)); waste_area_m2 = waste_length_m * (required_material_width_mm / 1000) if required_material_width_mm > 0 else 0.0; results['waste_length_m'] = waste_length_m; results['waste_area_m2'] = waste_area_m2; total_final_length_m = total_production_length_m + waste_length_m; total_final_area_m2 = total_production_area_m2 + waste_area_m2; results['total_final_length_m'] = total_final_length_m; results['total_final_area_m2'] = total_final_area_m2; setup_time_min = num_colors_for_waste_time * SETUP_TIME_PER_COLOR_OR_BASE; production_time_min = (total_production_length_m / machine_speed_m_min) if machine_speed_m_min > 0 else 0.0; cleanup_time_min = CLEANUP_TIME_MIN; total_time_min = setup_time_min + production_time_min + cleanup_time_min; results['total_time_min'] = total_time_min; ink_cost_rsd = 0.0; ink_consumption_kg = 0.0; varnish_cost_rsd = 0.0; varnish_consumption_kg = 0.0
    if not is_blank and num_colors > 0 and total_production_area_m2 > 0: ink_consumption_kg = (total_production_area_m2 * num_colors * GRAMS_INK_PER_M2) / 1000.0; ink_cost_rsd = ink_consumption_kg * ink_price_kg
    if is_uv_varnish and total_production_area_m2 > 0: varnish_consumption_kg = (total_production_area_m2 * GRAMS_VARNISH_PER_M2) / 1000.0; varnish_cost_rsd = varnish_consumption_kg * varnish_price_kg
    total_ink_varnish_cost_rsd = ink_cost_rsd + varnish_cost_rsd; results['ink_cost_rsd'] = ink_cost_rsd; results['varnish_cost_rsd'] = varnish_cost_rsd; total_plate_cost_rsd = (num_colors * plate_price_color) if not is_blank and num_colors > 0 else 0.0; results['plate_cost_rsd'] = total_plate_cost_rsd; total_material_cost_rsd = total_final_area_m2 * price_per_m2 if total_final_area_m2 > 0 and price_per_m2 >= 0 else 0.0; results['material_cost_rsd'] = total_material_cost_rsd; total_machine_labor_cost_rsd = (total_time_min / 60.0) * labor_price_hour if total_time_min > 0 and labor_price_hour >= 0 else 0.0; results['labor_cost_rsd'] = total_machine_labor_cost_rsd; total_tool_cost_rsd = 0.0
    if selected_tool_key == "Semirotary": total_tool_cost_rsd = tool_price_semi
    elif selected_tool_key == "Rotary": total_tool_cost_rsd = tool_price_rot
    results['tool_cost_rsd'] = total_tool_cost_rsd;
    # Nema više placeholder-a za technology_code
    total_production_cost_rsd = (total_ink_varnish_cost_rsd + total_plate_cost_rsd + total_material_cost_rsd + total_machine_labor_cost_rsd + total_tool_cost_rsd); results['total_production_cost_rsd'] = total_production_cost_rsd; profit_rsd = total_material_cost_rsd * profit_coefficient if total_material_cost_rsd > 0 and profit_coefficient > 0 else 0.0; results['profit_rsd'] = profit_rsd; results['profit_coefficient_used'] = profit_coefficient; total_selling_price_rsd = total_production_cost_rsd + profit_rsd; selling_price_per_piece_rsd = (total_selling_price_rsd / quantity) if quantity > 0 else 0.0; results['total_selling_price_rsd'] = total_selling_price_rsd; results['selling_price_per_piece_rsd'] = selling_price_per_piece_rsd; results['setup_time_min'] = setup_time_min; results['production_time_min'] = production_time_min; results['cleanup_time_min'] = cleanup_time_min
    return results

# --- PDF Generation Functions ---
# (create_pdf - AŽURIRAN: Uklonjena Technology iz parametara)
def create_pdf(data):
    buffer = io.BytesIO(); styles = getSampleStyleSheet(); doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    story = []; styleN = styles['Normal']; 
    def bold_paragraph(text): return Paragraph(f"<b>{text}</b>", styleN)
    story.append(Paragraph("Print Calculation Report", styles['h1'])); story.append(Spacer(1, 6*mm))
    story.append(Paragraph(f"<b>Client:</b> {data.get('client_name', 'N/A')}", styleN)); story.append(Paragraph(f"<b>Product/Label:</b> {data.get('product_name', 'N/A')}", styleN)); story.append(Paragraph(f"<b>Date Generated:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styleN)); story.append(Spacer(1, 6*mm))
    story.append(Paragraph("Input Parameters Summary", styles['h2']))
    # Uklonjena Technology
    params_data = [['Parameter', 'Value'], ['Template Width (W)', f"{data.get('template_width_W_input', 'N/A'):.3f} mm"], ['Template Height (H)', f"{data.get('template_height_H_input', 'N/A'):.3f} mm"], ['Desired Quantity', f"{data.get('quantity_input', 'N/A'):,}"], ['Colors', 'Blank' if data.get('is_blank') else f"{data.get('valid_num_colors_for_calc', 'N/A')}"], ['UV Varnish', 'Yes' if data.get('is_uv_varnish_input') else 'No'], ['Material', f"{data.get('selected_material', 'N/A')}"], ['Tool', f"{data.get('tool_info_string', 'N/A')}"], ['Machine Speed', f"{data.get('machine_speed_m_min', 'N/A')} m/min"], ['Profit Coefficient (Used)', f"{data.get('profit_coefficient_used', 'N/A'):.3f}"]]
    params_table = Table(params_data, colWidths=[80*mm, 80*mm]); params_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.grey), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('ALIGN', (0, 0), (-1, -1), 'LEFT'), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('BOTTOMPADDING', (0, 0), (-1, 0), 12), ('BACKGROUND', (0, 1), (-1, -1), colors.beige), ('GRID', (0, 0), (-1, -1), 1, colors.black)])); story.append(params_table); story.append(Spacer(1, 6*mm))
    story.append(Paragraph("Calculation Results", styles['h2'])); story.append(Paragraph("1. Cylinder and Template Configuration", styles['h3']))
    bc_sol = data.get('best_circumference_solution', {}); config_data = [['Item', 'Value'], ['Number of Teeth (Z)', f"{bc_sol.get('number_of_teeth_Z', 'N/A')}"], ['Cylinder Circumference', f"{bc_sol.get('circumference_mm', 0.0):.3f} mm"], ['Circumference Gap (G)', f"{data.get('gap_G_circumference_mm', 0.0):.3f} mm"], ['Templates Circumference (x)', f"{data.get('number_circumference_x', 'N/A')}"], ['Templates Width (y)', f"{data.get('number_across_width_y', 'N/A')}"], ['Format (y × x)', f"{data.get('number_across_width_y', 'N/A')} × {data.get('number_circumference_x', 'N/A')}"]]
    config_table = Table(config_data, colWidths=[80*mm, 80*mm]); config_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.darkblue), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('ALIGN', (0, 0), (-1, -1), 'LEFT'), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('BOTTOMPADDING', (0, 0), (-1, 0), 12), ('GRID', (0, 0), (-1, -1), 1, colors.black)])); story.append(config_table); story.append(Spacer(1, 4*mm))
    story.append(Paragraph("2. Material Width", styles['h3'])); mat_width_status = f"OK (≤ {MAX_MATERIAL_WIDTH} mm)" if not data.get('material_width_exceeded') else f"⚠️ EXCEEDED! (> {MAX_MATERIAL_WIDTH} mm)"; story.append(Paragraph(f"Required Material Width: {data.get('required_material_width_mm', 0.0):.2f} mm ({mat_width_status})", styleN)); story.append(Spacer(1, 4*mm))
    story.append(Paragraph("3. Material Consumption", styles['h3'])); consumption_data_styled = [['Category', 'Length (m)', 'Area (m²)'], ['Production', f"{data.get('total_production_length_m', 0.0):,.2f}", f"{data.get('total_production_area_m2', 0.0):,.2f}"], ['Waste (Setup)', f"{data.get('waste_length_m', 0.0):,.2f}", f"{data.get('waste_area_m2', 0.0):,.2f}"], [bold_paragraph('TOTAL'), bold_paragraph(f"{data.get('total_final_length_m', 0.0):,.2f}"), bold_paragraph(f"{data.get('total_final_area_m2', 0.0):,.2f}")]]
    consumption_table = Table(consumption_data_styled, colWidths=[50*mm, 55*mm, 55*mm]); consumption_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.darkblue), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('BOTTOMPADDING', (0, 0), (-1, 0), 12), ('GRID', (0, 0), (-1, -1), 1, colors.black)])); story.append(consumption_table); story.append(Spacer(1, 4*mm))
    story.append(Paragraph("4. Estimated Production Time", styles['h3'])); time_data_styled = [['Setup Time', format_time(data.get('setup_time_min', 0.0))], ['Production Time', format_time(data.get('production_time_min', 0.0))], ['Cleanup Time', format_time(data.get('cleanup_time_min', 0.0))], [bold_paragraph('TOTAL Work Time'), bold_paragraph(format_time(data.get('total_time_min', 0.0)))]]
    time_table = Table(time_data_styled, colWidths=[80*mm, 80*mm]); time_table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'LEFT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('GRID', (0, 0), (-1, -1), 1, colors.black)])); story.append(time_table); story.append(Spacer(1, 6*mm))
    story.append(Paragraph("Cost Calculation", styles['h2'])); cost_data_styled = [['Cost Item', 'Amount (RSD)'], ['Ink + Varnish', f"{data.get('total_ink_varnish_cost_rsd', 0.0):,.2f}"], ['Plates', f"{data.get('plate_cost_rsd', 0.0):,.2f}"], ['Material', f"{data.get('material_cost_rsd', 0.0):,.2f}"], ['Tool', f"{data.get('tool_cost_rsd', 0.0):,.2f}"], ['Machine Labor', f"{data.get('labor_cost_rsd', 0.0):,.2f}"], [bold_paragraph('Total Production Cost'), bold_paragraph(f"{data.get('total_production_cost_rsd', 0.0):,.2f}")]]
    cost_table = Table(cost_data_styled, colWidths=[80*mm, 80*mm]); cost_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.darkgreen), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('ALIGN', (0, 0), (-1, -1), 'LEFT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('BOTTOMPADDING', (0, 0), (-1, 0), 12), ('BACKGROUND', (0, 1), (-1, -2), colors.lightgreen), ('BACKGROUND', (0, 6), (-1, 6), colors.darkseagreen), ('GRID', (0, 0), (-1, -1), 1, colors.black)])); story.append(cost_table); story.append(Spacer(1, 6*mm))
    story.append(Paragraph("Final Price Summary", styles['h2'])); final_price_data_styled = [['Item', 'Amount (RSD)'], ['Total Production Cost', f"{data.get('total_production_cost_rsd', 0.0):,.2f}"], ['Profit', f"{data.get('profit_rsd', 0.0):,.2f} ({data.get('profit_coefficient_used', 0.0)*100:.1f}%)"], [bold_paragraph('TOTAL PRICE (Selling)'), bold_paragraph(f"{data.get('total_selling_price_rsd', 0.0):,.2f}")], ['Selling Price per Piece', f"{data.get('selling_price_per_piece_rsd', 0.0):.4f}"]]
    final_price_table = Table(final_price_data_styled, colWidths=[80*mm, 80*mm]); final_price_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.darkred), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('ALIGN', (0, 0), (-1, -1), 'LEFT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('BOTTOMPADDING', (0, 0), (-1, 0), 12), ('BACKGROUND', (0, 1), (-1, -1), colors.antiquewhite), ('BACKGROUND', (0, 3), (-1, 3), colors.lightcoral), ('GRID', (0, 0), (-1, -1), 1, colors.black)])); story.append(final_price_table)
    try: doc.build(story); buffer.seek(0); return buffer
    except Exception as e: st.error(f"Error building PDF: {e}"); return None

# (PDF Ponude - AŽURIRAN: Uklonjena Šifra Tehnologije iz specifikacije)
def create_offer_pdf(data):
    buffer = io.BytesIO(); doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm, topMargin=20*mm, bottomMargin=20*mm)
    styles = getSampleStyleSheet(); story = []; styleNormal = styles['Normal']
    styleH1_Offer = ParagraphStyle(name='OfferTitle', parent=styles['h1'], alignment=TA_CENTER, spaceAfter=10*mm); styleH2_Offer = ParagraphStyle(name='OfferHeading', parent=styles['h2'], spaceBefore=6*mm, spaceAfter=4*mm)
    styleItalic = ParagraphStyle(name='ItalicText', parent=styleNormal, fontName='Helvetica-Oblique', fontSize=9); 
    def bold_paragraph(text): return Paragraph(f"<b>{text}</b>", styleNormal)
    story.append(Paragraph("PONUDA / OFFER", styleH1_Offer)); offer_date = datetime.datetime.now().strftime('%d.%m.%Y')
    story.append(Paragraph(f"<b>Datum / Date:</b> {offer_date}", styleNormal)); story.append(Paragraph(f"<b>Za / To:</b> {data.get('client_name', 'N/A')}", styleNormal)); story.append(Spacer(1, 6*mm))
    story.append(Paragraph(f"<b>Predmet / Subject:</b> Ponuda za izradu samolepljivih etiketa / Offer for self-adhesive label production", styleNormal)); story.append(Paragraph(f"<b>Proizvod / Product:</b> {data.get('product_name', 'N/A')}", styleNormal)); story.append(Spacer(1, 6*mm))
    story.append(Paragraph("Specifikacija / Specification:", styleH2_Offer)); spec_list_data = data.get('specifications', {});
    # Uklonjena Šifra Tehnologije iz specifikacije za PDF ponude
    spec_table_data = [ [bold_paragraph(k), v] for k, v in spec_list_data.items() if k != "Šifra Tehnologije" ]
    spec_table = Table(spec_table_data, colWidths=[50*mm, 110*mm]); spec_table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'LEFT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('GRID', (0, 0), (-1, -1), 0.5, colors.grey), ('BOTTOMPADDING', (0, 0), (-1, -1), 3*mm), ('TOPPADDING', (0, 0), (-1, -1), 3*mm)])); story.append(spec_table); story.append(Spacer(1, 8*mm))
    story.append(Paragraph("Cene / Prices:", styleH2_Offer)); offer_results = data.get('offer_results', []); price_table_data = [[bold_paragraph("Količina (kom)"), bold_paragraph("Cena/kom (RSD)"), bold_paragraph("Ukupno (RSD)")]]
    for row in offer_results: price_table_data.append([ f"{row.get('Količina (kom)', 0):,}", f"{row.get('Cena/kom (RSD)', 0.0):.4f}", f"{row.get('Ukupno (RSD)', 0.0):,.2f}" ])
    if len(price_table_data) > 1:
        price_table = Table(price_table_data, colWidths=[50*mm, 55*mm, 55*mm])
        price_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.darkgrey), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('ALIGN', (0, 0), (-1, 0), 'CENTER'), ('ALIGN', (0, 1), (0, -1), 'RIGHT'), ('ALIGN', (1, 1), (-1, -1), 'RIGHT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('BOTTOMPADDING', (0, 0), (-1, -1), 3*mm), ('TOPPADDING', (0, 0), (-1, -1), 3*mm), ('GRID', (0, 0), (-1, -1), 1, colors.black)])); story.append(price_table); story.append(Spacer(1, 4*mm))
        story.append(Paragraph("<i>Napomena: U cene nije uključen PDV. Cena alata je uključena u ukupnu cenu (ako je primenjivo).</i>", styleItalic)); story.append(Paragraph("<i>Note: VAT is not included. Tool cost is included in the total price (if applicable).</i>", styleItalic))
    else: story.append(Paragraph("Nema dostupnih cena za prikaz.", styleNormal))
    story.append(Spacer(1, 10*mm)); story.append(Paragraph("<b>Rok isporuke / Delivery Time:</b> Po dogovoru / As agreed", styleNormal)); story.append(Paragraph("<b>Paritet / Incoterms:</b> FCO magacin Kupca / FCO Buyer's warehouse", styleNormal)); story.append(Paragraph("<b>Validnost ponude / Offer Validity:</b> 15 dana / 15 days", styleNormal))
    try: doc.build(story); buffer.seek(0); return buffer
    except Exception as e: st.error(f"Error building Offer PDF: {e}"); return None

# --- Helper funkcija za sinhronizaciju ---
def synced_number_input(label, state_key, db_key, min_val=0.0, step=1.0, format_str="%.2f", help_text=None):
    if state_key not in st.session_state: fallback_val = st.session_state.settings.get(db_key, min_val if min_val > 0 else 0.0); st.session_state[state_key] = fallback_val
    current_val_from_state = st.session_state[state_key]
    input_val = st.sidebar.number_input(label, min_value=min_val, value=current_val_from_state, step=step, format=format_str, key=f"{state_key}_input_widget", help=help_text)
    if not math.isclose(input_val, current_val_from_state, rel_tol=1e-7, abs_tol=1e-7):
        st.session_state[state_key] = input_val
        if update_setting_in_db(db_key, input_val): pass
        else: st.sidebar.error(f"Failed to update {label} in DB.") # Grešku možemo prikazati ovde
        st.rerun()
    return input_val

# --- Inicijalizacija baze na početku ---
db_init_success = init_db()

# --- Session State Initialization ---
if 'db_loaded' not in st.session_state:
    st.session_state.db_init_success = db_init_success
    if db_init_success:
        st.session_state.materials_prices = load_materials_from_db()
        st.session_state.settings = load_settings_from_db()
        if st.session_state.settings is None: st.session_state.settings = {}; db_load_error = True
        else: db_load_error = False
        st.session_state.ink_price_per_kg = st.session_state.settings.get('ink_price_per_kg', FALLBACK_INK_PRICE)
        st.session_state.varnish_price_per_kg = st.session_state.settings.get('varnish_price_per_kg', FALLBACK_VARNISH_PRICE)
        st.session_state.machine_labor_price_per_hour = st.session_state.settings.get('machine_labor_price_per_hour', FALLBACK_LABOR_PRICE)
        st.session_state.tool_price_semirotary = st.session_state.settings.get('tool_price_semirotary', FALLBACK_TOOL_SEMI_PRICE)
        st.session_state.tool_price_rotary = st.session_state.settings.get('tool_price_rotary', FALLBACK_TOOL_ROT_PRICE)
        st.session_state.plate_price_per_color = st.session_state.settings.get('plate_price_per_color', FALLBACK_PLATE_PRICE)
        st.session_state.machine_speed_default = int(st.session_state.settings.get('machine_speed_default', FALLBACK_MACHINE_SPEED))
        st.session_state.single_calc_profit_coefficient = st.session_state.settings.get('single_calc_profit_coefficient', FALLBACK_SINGLE_PROFIT)
        for qty in QUANTITIES_FOR_OFFER: key = f"profit_coeff_{qty}"; st.session_state[key] = st.session_state.settings.get(key, FALLBACK_PROFITS.get(qty, 0.20))
        if db_load_error: st.error("Failed to load settings from database! Using fallback values.") # Greška se prikazuje ovde
        if st.session_state.materials_prices is None: st.error("Failed to load materials from database! Using fallback values."); st.session_state.materials_prices = {"Paper (chrome)": 39.95}
    else:
        st.error("CRITICAL DATABASE INITIALIZATION FAILED! Using fallback values.")
        st.session_state.materials_prices = {"Paper (chrome)": 39.95}; st.session_state.settings = {}
        st.session_state.ink_price_per_kg = FALLBACK_INK_PRICE; st.session_state.varnish_price_per_kg = FALLBACK_VARNISH_PRICE; st.session_state.machine_labor_price_per_hour = FALLBACK_LABOR_PRICE; st.session_state.tool_price_semirotary = FALLBACK_TOOL_SEMI_PRICE; st.session_state.tool_price_rotary = FALLBACK_TOOL_ROT_PRICE; st.session_state.plate_price_per_color = FALLBACK_PLATE_PRICE; st.session_state.machine_speed_default = FALLBACK_MACHINE_SPEED; st.session_state.single_calc_profit_coefficient = FALLBACK_SINGLE_PROFIT;
        for qty in QUANTITIES_FOR_OFFER: key = f"profit_coeff_{qty}"; st.session_state[key] = FALLBACK_PROFITS.get(qty, 0.20)
    st.session_state.existing_tool_info = ""; st.session_state.offer_results_list = []; st.session_state.offer_pdf_buffer = None; st.session_state.show_history_check_state = False; st.session_state.db_loaded = True

# --- Streamlit Application UI ---
st.title("📊 Label Printing Cost Calculator & Offer Generator (DB Connected)")
st.markdown("Enter parameters in the sidebar. Calculation is shown below. Generate a multi-quantity offer at the bottom.")

if not st.session_state.get('db_init_success', False):
     st.error("Critical database error during initialization. Application cannot proceed reliably.")
     st.stop()

# --- Sidebar ---
st.sidebar.header("Input Parameters")
client_name = st.sidebar.text_input("Client Name:", key="client_name_input")
product_name = st.sidebar.text_input("Product/Label Name:", key="product_name_input")
st.sidebar.markdown("---")
template_width_W_input = st.sidebar.number_input("Template Width (W, mm):", min_value=0.1, value=76.0, step=0.1, format="%.3f", key="template_width_input")
template_height_H_input = st.sidebar.number_input("Template Height (H, mm):", min_value=0.1, value=76.0, step=0.1, format="%.3f", key="template_height_input")
quantity_input = st.sidebar.number_input("Desired Quantity (for single calc):", min_value=1, value=10000, step=1000, format="%d", key="quantity_input")
# Nema više Šifre Tehnologije ovde
st.sidebar.markdown("---"); st.sidebar.subheader("Ink, Varnish, and Plate Settings")
is_blank = st.sidebar.checkbox("Blank Template (no ink)", value=False, key="is_blank_check")
num_colors_input = st.sidebar.number_input("Number of Colors:", min_value=1, max_value=8, value=1, step=1, format="%d", disabled=is_blank, key="num_colors_select")
is_uv_varnish_input = st.sidebar.checkbox("UV Varnish", value=False, help=f"{GRAMS_VARNISH_PER_M2}g/m²", key="is_uv_varnish_check")
ink_price_kg_input = synced_number_input("Ink Price (RSD/kg):", 'ink_price_per_kg', 'ink_price_per_kg', step=10.0)
varnish_price_kg_input = synced_number_input("UV Varnish Price (RSD/kg):", 'varnish_price_per_kg', 'varnish_price_per_kg', step=10.0)
plate_price_input = synced_number_input("Plate Price per Color (RSD):", 'plate_price_per_color', 'plate_price_per_color', step=50.0)
st.sidebar.markdown("---"); st.sidebar.subheader("Machine")
machine_speed_m_min = st.sidebar.slider("Average Machine Speed (m/min):", MACHINE_SPEED_MIN, MACHINE_SPEED_MAX, st.session_state.machine_speed_default, 5, key="machine_speed_slider")
labor_price_h_input = synced_number_input("Machine Labor Price (RSD/h):", 'machine_labor_price_per_hour', 'machine_labor_price_per_hour', step=50.0)
st.sidebar.markdown("---"); st.sidebar.subheader("Cutting Tool")
tool_type_options_keys = ["None", "Semirotary", "Rotary"]
selected_tool_key = st.sidebar.radio("Select tool type:", options=tool_type_options_keys, index=0, key="tool_type_radio")
existing_tool_info_input = ""
if selected_tool_key == "None": st.session_state.existing_tool_info = st.sidebar.text_input("Existing tool ID/Name:", value=st.session_state.existing_tool_info, help="Enter identifier.", key="existing_tool_text_input"); existing_tool_info_input = st.session_state.existing_tool_info
tool_price_semi_input = synced_number_input("Semirotary Tool Price (RSD):", 'tool_price_semirotary', 'tool_price_semirotary', step=100.0)
tool_price_rot_input = synced_number_input("Rotary Tool Price (RSD):", 'tool_price_rotary', 'tool_price_rotary', step=100.0)
st.sidebar.markdown("---"); st.sidebar.subheader("Material")
material_list = list(st.session_state.get('materials_prices', {}).keys())
if not material_list: st.sidebar.error("No materials found!"); selected_material = None; current_material_price_state = 0.0; price_per_m2_input = 0.0
else:
    default_index = 0 if material_list else -1; selected_material = st.sidebar.selectbox("Select material type:", options=material_list, index=default_index, key="material_select")
    current_material_price_state = st.session_state.materials_prices.get(selected_material, 0.0) if selected_material else 0.0
material_price_label_formatted = f"Price for '{selected_material}' (RSD/m²):" if selected_material else "Material Price (RSD/m²):"
price_per_m2_input = st.sidebar.number_input(material_price_label_formatted, min_value=0.0, value=current_material_price_state, step=0.1, format="%.2f", key="material_price_input_widget", disabled=(selected_material is None))
if selected_material and not math.isclose(price_per_m2_input, current_material_price_state):
    st.session_state.materials_prices[selected_material] = price_per_m2_input
    if update_material_price_in_db(selected_material, price_per_m2_input): pass
    else: st.sidebar.error(f"Failed to update price for {selected_material}.")
    st.rerun()
with st.sidebar.expander("➕ Add New Material"):
    new_material_name = st.text_input("New Material Name", key="new_mat_name"); new_material_price = st.number_input("New Material Price (RSD/m²)", min_value=0.0, step=0.1, format="%.2f", key="new_mat_price")
    if st.button("Add Material", key="add_mat_button"):
        if new_material_name and new_material_price > 0:
            conn_add = get_db_connection()
            if conn_add:
                try: cursor_add = conn_add.cursor(); cursor_add.execute("INSERT INTO materials (name, price_per_m2) VALUES (?, ?)", (new_material_name, new_material_price)); conn_add.commit(); st.session_state.materials_prices = load_materials_from_db(); st.sidebar.success(f"Material '{new_material_name}' added!"); st.rerun()
                except sqlite3.IntegrityError: st.sidebar.error(f"Material '{new_material_name}' already exists.")
                except sqlite3.Error as e: st.sidebar.error(f"DB Error adding material: {e}")
                finally: conn_add.close()
        else: st.sidebar.warning("Please enter both name and price > 0.")
st.sidebar.markdown("---"); st.sidebar.subheader("Profit Coefficient (Single Calc)")
st.sidebar.caption("Used only for the calculation shown at the top.")
single_calc_profit_input = synced_number_input(label="Profit Coeff:", state_key='single_calc_profit_coefficient', db_key='single_calc_profit_coefficient', min_val=0.00, step=0.01, format_str="%.3f")
st.sidebar.markdown("---"); st.sidebar.subheader("Profit Coefficients (Offer)")
st.sidebar.caption("Used only when generating the multi-quantity offer.")
profit_coeffs_inputs = {};
for qty in QUANTITIES_FOR_OFFER: state_key = f'profit_coeff_{qty}'; db_key = f'profit_coeff_{qty}'; profit_coeffs_inputs[qty] = synced_number_input(label=f"Coeff. for {qty:,}:", state_key=state_key, db_key=db_key, min_val=0.00, step=0.01, format_str="%.3f")

# --- Main Calculation & Display Area ---
st.header("📊 Calculation Results (Single Quantity)")

inputs_valid = (template_width_W_input and template_height_H_input and quantity_input > 0 and machine_speed_m_min and selected_material and price_per_m2_input is not None and labor_price_h_input is not None and selected_tool_key is not None and st.session_state.single_calc_profit_coefficient is not None) # Uklonjena provera za tech_code
pdf_buffer = None; calculation_data_for_db = {}; single_calc_result = {}; best_circumference_solution = None; number_across_width_y = 0; tool_info_string = ""
current_calc_params = {}

if inputs_valid:
    best_circumference_solution, all_circumference_solutions, circumference_message = find_cylinder_specifications(template_width_W_input)
    number_across_width_y = calculate_number_across_width(template_height_H_input, WORKING_WIDTH, WIDTH_GAP)
    tool_info_string = f"Existing: {existing_tool_info_input}" if selected_tool_key == "None" and existing_tool_info_input else selected_tool_key

    if best_circumference_solution:
        single_profit_coeff = st.session_state.get('single_calc_profit_coefficient')
        if single_profit_coeff is None: st.error("Error: Single Profit Coefficient not found."); single_calc_result = {'error': 'Missing profit coefficient'}
        else:
            current_calc_params = { "quantity": quantity_input, "template_width_W": template_width_W_input, "template_height_H": template_height_H_input, "best_circumference_solution": best_circumference_solution, "number_across_width_y": number_across_width_y, "is_blank": is_blank, "num_colors": 0 if is_blank else (num_colors_input if num_colors_input >= 1 else 1), "is_uv_varnish": is_uv_varnish_input, "price_per_m2": price_per_m2_input, "machine_speed_m_min": machine_speed_m_min, "selected_tool_key": selected_tool_key, "existing_tool_info": existing_tool_info_input, "profit_coefficient": single_profit_coeff, "ink_price_kg": st.session_state.ink_price_per_kg, "varnish_price_kg": st.session_state.varnish_price_per_kg, "plate_price_color": st.session_state.plate_price_per_color, "labor_price_hour": st.session_state.machine_labor_price_per_hour, "tool_price_semi": st.session_state.tool_price_semirotary, "tool_price_rot": st.session_state.tool_price_rotary
                                  # Nema technology_code
                               }
            single_calc_result = run_single_calculation(**current_calc_params) # Poziv bez technology_code

        if 'error' not in single_calc_result:
            st.subheader(f"Details for Qty: {quantity_input:,} pcs (using Profit Coeff: {single_profit_coeff:.3f})")
            with st.expander("Calculation Details (Config, Consumption, Time)"):
                 # Uklonjen Tech iz prikaza parametara
                 num_colors_calc = current_calc_params.get('num_colors', 0); params_dims = f"W:{template_width_W_input:.2f}×H:{template_height_H_input:.2f}mm"; params_qty = f"Qty:{quantity_input:,}"; params_colors = 'Blank' if is_blank else str(num_colors_calc)+'C'; params_varnish = '+V' if is_uv_varnish_input else ''; params_mat = f"Mat:'{selected_material}'"; params_tool = f"Tool:'{tool_info_string}'"; params_speed = f"Speed:{machine_speed_m_min}m/min"; params_profit = f"Prof.Coef:{single_profit_coeff:.3f}"; st.write(f"**Parameters:** {params_dims} | {params_qty} | {params_colors}{params_varnish} | {params_mat} | {params_tool} | {params_speed} | {params_profit}"); st.markdown("---")
                 st.subheader("1. Cylinder & Template"); col1, col2 = st.columns(2);
                 with col1: st.metric("Teeth (Z)", f"{best_circumference_solution.get('number_of_teeth_Z', 'N/A')}"); st.metric("Circumference", f"{best_circumference_solution.get('circumference_mm', 0.0):.3f} mm"); st.metric("Gap (G)", f"{best_circumference_solution.get('gap_G_circumference_mm', 0.0):.3f} mm")
                 with col2: st.metric("Templates (x)", f"{best_circumference_solution.get('templates_N_circumference', 'N/A')}"); st.metric("Templates (y)", f"{number_across_width_y}"); st.metric("Format (y×x)", f"{number_across_width_y}×{best_circumference_solution.get('templates_N_circumference', 'N/A')}")
                 st.subheader("2. Material Width")
                 if number_across_width_y > 0:
                     mat_col1a, mat_col2a = st.columns([2,1]); help_width_a = f"({number_across_width_y}×{template_height_H_input:.2f})+({max(0, number_across_width_y-1)}×{WIDTH_GAP})+{WIDTH_WASTE}"; req_w = single_calc_result.get('required_material_width_mm', 0); 
                     with mat_col1a: st.metric("Required Width", f"{req_w:.2f} mm", help=help_width_a); 
                     with mat_col2a:
                        if not single_calc_result.get('material_width_exceeded'): st.success(f"✅ OK (≤ {MAX_MATERIAL_WIDTH} mm)") 
                        else: st.error(f"⚠️ EXCEEDED! (> {MAX_MATERIAL_WIDTH} mm)")
                 else: st.warning("y=0, N/A")
                 st.subheader("3/4. Material Consumption (Prod+Waste)"); tot_len = single_calc_result.get('total_final_length_m', 0); tot_area = single_calc_result.get('total_final_area_m2', 0); prod_len = single_calc_result.get('total_production_length_m', 0); waste_len = single_calc_result.get('waste_length_m', 0); tot_col1a, tot_col2a = st.columns(2); 
                 with tot_col1a: st.metric("TOTAL Length", f"{tot_len:,.2f} m", help=f"Prod:{prod_len:,.1f}m+Waste:{waste_len:,.1f}m"); 
                 with tot_col2a: st.metric("TOTAL Area", f"{tot_area:,.2f} m²")
                 st.subheader("5. Estimated Production Time"); time_col1a, time_col2a, time_col3a, time_col4a = st.columns(4); t_setup = single_calc_result.get('setup_time_min', 0); t_prod = single_calc_result.get('production_time_min', 0); t_clean = single_calc_result.get('cleanup_time_min', 0); t_total = single_calc_result.get('total_time_min', 0); 
                 with time_col1a: st.metric("Setup", format_time(t_setup)); 
                 with time_col2a: st.metric("Production", format_time(t_prod)); 
                 with time_col3a: st.metric("Cleanup", format_time(t_clean)); 
                 with time_col4a: st.metric("TOTAL", format_time(t_total))
            st.markdown("---"); st.subheader(f"💰 Costs & Final Price for Qty: {quantity_input:,}")
            cost_cols = st.columns(6); cost_cols[0].metric("Ink", f"{single_calc_result.get('ink_cost_rsd', 0):,.2f} RSD"); cost_cols[1].metric("Varnish", f"{single_calc_result.get('varnish_cost_rsd', 0):,.2f} RSD"); cost_cols[2].metric("Plates", f"{single_calc_result.get('plate_cost_rsd', 0):,.2f} RSD"); cost_cols[3].metric("Material", f"{single_calc_result.get('material_cost_rsd', 0):,.2f} RSD"); cost_cols[4].metric("Tool", f"{single_calc_result.get('tool_cost_rsd', 0):,.2f} RSD", help=tool_info_string); cost_cols[5].metric("Labor", f"{single_calc_result.get('labor_cost_rsd', 0):,.2f} RSD")
            price_cols = st.columns(3); price_cols[0].metric("Total Prod. Cost", f"{single_calc_result.get('total_production_cost_rsd', 0):,.2f} RSD");
            profit_value = single_calc_result.get('profit_rsd', 0); profit_coeff_used = single_calc_result.get('profit_coefficient_used', None); profit_delta_str = f"{profit_coeff_used*100:.1f}%" if profit_coeff_used is not None else None
            price_cols[1].metric("Profit", f"{profit_value:,.2f} RSD", delta=profit_delta_str)
            price_cols[2].metric("TOTAL SELLING PRICE", f"{single_calc_result.get('total_selling_price_rsd', 0):,.2f} RSD")
            st.metric("Selling Price / Piece", f"{single_calc_result.get('selling_price_per_piece_rsd', 0):.4f} RSD")
            # Priprema podataka za DB i PDF BEZ technology_code
            calculation_data_for_db = { "client_name": client_name, "product_name": product_name, "template_width_W_input": template_width_W_input, "template_height_H_input": template_height_H_input, "quantity_input": quantity_input, "is_blank": is_blank, "valid_num_colors_for_calc": current_calc_params.get('num_colors', 0), "is_uv_varnish_input": is_uv_varnish_input, "selected_material": selected_material, "tool_info_string": tool_info_string, "machine_speed_m_min": machine_speed_m_min, "best_circumference_solution": best_circumference_solution, "gap_G_circumference_mm": best_circumference_solution.get('gap_G_circumference_mm', 0), "number_circumference_x": best_circumference_solution.get('templates_N_circumference', 0), "number_across_width_y": number_across_width_y, **single_calc_result }
            pdf_buffer = create_pdf(calculation_data_for_db)
        else: st.error(f"Calculation failed for Qty {quantity_input}: {single_calc_result.get('error', 'Unknown calculation error')}")
    else: error_msg = circumference_message or "Circumference calculation failed."; st.error(f"❌ Cannot proceed: {error_msg}")
else:
    if not st.session_state.get('db_loaded', False): st.warning("Initializing database...")
    else: st.info("Enter all parameters in the left sidebar.")

# --- Offer Generation Section ---
st.markdown("---"); st.header("📋 Offer Generation (Multiple Quantities)")
offer_button_disabled = not (inputs_valid and best_circumference_solution and current_calc_params and 'error' not in single_calc_result)
if st.button("🔄 Preview/Update Offer Prices", key="preview_offer_button", disabled=offer_button_disabled):
    temp_offer_results_preview = []; progress_bar_preview = st.progress(0)
    with st.spinner("Calculating preview prices..."):
        base_params_for_preview = current_calc_params.copy()
        if base_params_for_preview:
            for i, qty in enumerate(QUANTITIES_FOR_OFFER):
                offer_params = base_params_for_preview.copy(); offer_params["quantity"] = qty; coeff_key = f'profit_coeff_{qty}'; specific_profit_coeff = st.session_state.get(coeff_key, FALLBACK_PROFITS.get(qty, 0.20)); offer_params["profit_coefficient"] = specific_profit_coeff
                # Pozivamo run_single_calculation BEZ technology_code argumenta
                result = run_single_calculation( quantity=offer_params["quantity"], template_width_W=offer_params["template_width_W"], template_height_H=offer_params["template_height_H"], best_circumference_solution=offer_params["best_circumference_solution"], number_across_width_y=offer_params["number_across_width_y"], is_blank=offer_params["is_blank"], num_colors=offer_params["num_colors"], is_uv_varnish=offer_params["is_uv_varnish"], price_per_m2=offer_params["price_per_m2"], machine_speed_m_min=offer_params["machine_speed_m_min"], selected_tool_key=offer_params["selected_tool_key"], existing_tool_info=offer_params["existing_tool_info"], profit_coefficient=offer_params["profit_coefficient"], ink_price_kg=offer_params["ink_price_kg"], varnish_price_kg=offer_params["varnish_price_kg"], plate_price_color=offer_params["plate_price_color"], labor_price_hour=offer_params["labor_price_hour"], tool_price_semi=offer_params["tool_price_semi"], tool_price_rot=offer_params["tool_price_rot"] )
                if 'error' not in result: temp_offer_results_preview.append({"Količina (kom)": qty, "Cena/kom (RSD)": result.get('selling_price_per_piece_rsd', 0), "Ukupno (RSD)": result.get('total_selling_price_rsd', 0)})
                else: st.warning(f"Calc failed for Qty {qty}: {result['error']}")
                progress_bar_preview.progress((i + 1) / len(QUANTITIES_FOR_OFFER))
            if temp_offer_results_preview: st.session_state.offer_results_list = temp_offer_results_preview; st.session_state.offer_pdf_buffer = None; st.rerun()
            else: st.warning("Offer price preview failed.")
        else: st.error("Cannot preview offer, base parameters missing.")

if st.session_state.offer_results_list:
    st.subheader("Offer Summary Preview")
    st.write(f"**Client:** {client_name if client_name else 'N/A'}"); st.write(f"**Product:** {product_name if product_name else 'N/A'}"); st.write("**Specifications:**")
    num_colors_display_offer = 0 if is_blank else (num_colors_input if num_colors_input >= 1 else 1)
    # Uklonjena Šifra Tehnologije iz specifikacije ponude
    spec_data_offer = {"Dimenzija (mm)": f"{template_width_W_input:.2f} x {template_height_H_input:.2f}", "Materijal": selected_material, "Broj boja": "Blank" if is_blank else num_colors_display_offer, "UV Lak": "Da" if is_uv_varnish_input else "Ne", "Alat": tool_info_string }
    spec_df_offer = pd.DataFrame(spec_data_offer.items(), columns=['Stavka', 'Vrednost']); st.dataframe(spec_df_offer, hide_index=True, use_container_width=True)
    st.write("**Prices per Quantity (Preview):**"); offer_df_display = pd.DataFrame(st.session_state.offer_results_list)
    offer_df_display['Cena/kom (RSD)'] = offer_df_display['Cena/kom (RSD)'].map('{:.4f}'.format); offer_df_display['Ukupno (RSD)'] = offer_df_display['Ukupno (RSD)'].map('{:,.2f}'.format)
    st.dataframe(offer_df_display, hide_index=True, use_container_width=True)
else: st.info("Click 'Preview/Update Offer Prices' to calculate and display the offer table based on current coefficients.")

# --- Action Buttons ---
st.markdown("---"); action_cols = st.columns(3)
with action_cols[0]:
    pdf_download_disabled = pdf_buffer is None
    if pdf_buffer: safe_product_name = "".join(c if c.isalnum() else "_" for c in product_name) if product_name else "product"; safe_client_name = "".join(c if c.isalnum() else "_" for c in client_name) if client_name else "client"; pdf_filename = f"Calc_{safe_product_name}_{safe_client_name}_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf"; st.download_button(label="📄 Download Calc PDF", data=pdf_buffer, file_name=pdf_filename, mime="application/pdf", key="pdf_calc_download", use_container_width=True, disabled=pdf_download_disabled)
    else: st.button("📄 Download Calc PDF", disabled=True, use_container_width=True, help="Valid calculation required.")
with action_cols[1]:
    save_disabled = not calculation_data_for_db
    if st.button("💾 Save Calc to DB", disabled=save_disabled, key="save_calc_button", use_container_width=True):
        if calculation_data_for_db:
            if save_calculation_to_db(calculation_data_for_db): st.success("Calculation saved to DB!")
with action_cols[2]:
     final_offer_button_disabled = not st.session_state.offer_results_list
     if st.button("📝 Generate Final Offer & PDF", key="generate_final_offer_button", disabled=final_offer_button_disabled, use_container_width=True):
         if st.session_state.offer_results_list and current_calc_params:
              num_colors_display_pdf = 0 if is_blank else (num_colors_input if num_colors_input >= 1 else 1)
              # Uklonjena Šifra Tehnologije iz specifikacije za PDF ponude
              spec_data_pdf = {"Dimenzija (mm)": f"{template_width_W_input:.2f} x {template_height_H_input:.2f}", "Materijal": selected_material, "Broj boja": "Blank" if is_blank else num_colors_display_pdf, "UV Lak": "Da" if is_uv_varnish_input else "Ne", "Alat": tool_info_string }
              offer_pdf_data = {"client_name": client_name, "product_name": product_name, "specifications": spec_data_pdf, "offer_results": st.session_state.offer_results_list}
              pdf_gen_buffer = create_offer_pdf(offer_pdf_data)
              if pdf_gen_buffer: st.session_state.offer_pdf_buffer = pdf_gen_buffer; st.success("Final Offer PDF generated!"); st.rerun()
              else: st.error("Failed to generate final offer PDF.")
         else: st.warning("No offer results available. Please Preview first.")
     offer_pdf_download_disabled = st.session_state.offer_pdf_buffer is None
     if st.session_state.offer_pdf_buffer: safe_product_name_offer = "".join(c if c.isalnum() else "_" for c in product_name) if product_name else "product"; safe_client_name_offer = "".join(c if c.isalnum() else "_" for c in client_name) if client_name else "client"; offer_pdf_filename = f"Offer_{safe_product_name_offer}_{safe_client_name_offer}_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.pdf"; st.download_button(label="⬇️ Download Offer PDF", data=st.session_state.offer_pdf_buffer, file_name=offer_pdf_filename, mime="application/pdf", key="pdf_offer_download_final", use_container_width=True)
     else: st.button("⬇️ Download Offer PDF", disabled=True, use_container_width=True, help="Generate Final Offer first.")

# --- History Display (Verzija koju ste tražili - sirovi podaci, BEZ technology_code) ---
st.markdown("---"); st.subheader("📜 Calculation History (Last 10)")
show_history = st.checkbox("Show History", value=st.session_state.show_history_check_state, key="show_history_widget"); st.session_state.show_history_check_state = show_history
if show_history:
    history_conn = get_db_connection()
    if history_conn:
        try:
            # SQL Upit BEZ technology_code
            history_df_raw = pd.read_sql_query( "SELECT timestamp, client_name, product_name, quantity, material_name, calculated_total_price, calculated_price_per_piece, profit_coefficient FROM calculations ORDER BY timestamp DESC LIMIT 10", history_conn )
            if not history_df_raw.empty:
                st.dataframe(history_df_raw, use_container_width=True)
            else: st.info("No calculations saved yet.")
        except Exception as e:
            # Proveravamo da li je greška zbog nepostojeće kolone (ako je baza starija)
            if "no such column: profit_coefficient" in str(e):
                 st.warning("Loading history failed. 'profit_coefficient' column might be missing in older records.")
                 # Pokušaj da učitaš bez te kolone
                 try:
                      history_df_raw = pd.read_sql_query( "SELECT timestamp, client_name, product_name, quantity, material_name, calculated_total_price, calculated_price_per_piece FROM calculations ORDER BY timestamp DESC LIMIT 10", history_conn )
                      if not history_df_raw.empty:
                           st.dataframe(history_df_raw, use_container_width=True)
                      else: st.info("No calculations saved yet.")
                 except Exception as e2:
                      st.error(f"Error loading history data (fallback attempt): {e2}")
            else:
                 st.error(f"Error loading history data: {e}")
                 st.exception(e)
        finally:
            history_conn.close()
    else:
        st.error("Could not connect to DB for history.")

# --- Footer ---
st.markdown("---")
settings_footer_str = (f"Current Base Settings: Labor: {st.session_state.machine_labor_price_per_hour:,.2f} | Ink: {st.session_state.ink_price_per_kg:,.2f}")
st.caption(settings_footer_str)
