from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from django.conf import settings
from .models import Assessment, Result
import requests
import math
import json
from datetime import datetime, timedelta
from django.template.loader import render_to_string
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
import io
import urllib.parse
from django.views.decorators.http import require_http_methods
from io import BytesIO
import uuid
import hashlib

OPENCAGE_API_KEY = 'fd8f381a99404d03857ca7b46f35b865'

# Enhanced Constants
SOLAR_EFFICIENCY = 0.20
PERFORMANCE_RATIO = 0.75
SOLAR_PANEL_AREA = 1.6
AIR_DENSITY = 1.225
WIND_TURBINE_RADIUS = 1.5
CP = 0.4
CO2_SAVED_PER_KWH = 0.42
WATER_DENSITY = 1000
GRAVITY = 9.81
HYDRO_EFFICIENCY = 0.9
BIOMASS_EFFICIENCY = 0.25
GEOTHERMAL_EFFICIENCY = 0.15
TREES_PER_TON_CO2 = 45

# Financial Constants
SOLAR_PANEL_COST_PER_WATT = 0.8  # USD
WIND_TURBINE_COST_PER_WATT = 1.2  # USD
HYDRO_COST_PER_WATT = 2.0  # USD
BIOMASS_COST_PER_WATT = 3.0  # USD
GEOTHERMAL_COST_PER_WATT = 4.0  # USD
BATTERY_COST_PER_KWH = 150  # USD
INVERTER_COST_PER_WATT = 0.3  # USD
MAINTENANCE_COST_PERCENT = 0.02  # 2% of CAPEX annually
ELECTRICITY_RATE = 0.12  # USD per kWh

def index(request):
    return render(request, 'index.html')

def get_cache_key(lat, lon, system_type):
    """Generate cache key for climate data"""
    return f"climate_data_{lat:.4f}_{lon:.4f}_{system_type}"

def get_nasa_power_data(lat, lon):
    """Fetch comprehensive climate data from NASA POWER API with caching"""
    cache_key = get_cache_key(lat, lon, "nasa")
    cached_data = cache.get(cache_key)
    
    if cached_data:
        return cached_data
    
    parameters = [
        'T2M', 'RH2M', 'PRECTOTCORR', 'WS10M', 'WD10M', 'PS',
        'ALLSKY_SFC_SW_DWN', 'CLRSKY_SFC_SW_DWN', 'TOA_SW_DWN',
        'QV2M', 'TQV'
    ]
    
    url = (
        f"https://power.larc.nasa.gov/api/temporal/climatology/point"
        f"?parameters={','.join(parameters)}"
        f"&community=RE&longitude={lon}&latitude={lat}&format=JSON"
    )
    
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        if 'properties' not in data or 'parameter' not in data['properties']:
            raise ValueError("Invalid response format from NASA POWER API")
        
        # Cache for 24 hours
        cache.set(cache_key, data['properties']['parameter'], 86400)
        return data['properties']['parameter']
        
    except Exception as e:
        raise Exception(f"Failed to fetch NASA POWER data: {str(e)}")

def calculate_financial_metrics(system_type, power_output, location_data):
    """Calculate comprehensive financial metrics"""
    yearly_kwh = power_output['yearly']
    
    # System costs based on type
    system_costs = {
        'solar': SOLAR_PANEL_COST_PER_WATT,
        'wind': WIND_TURBINE_COST_PER_WATT,
        'hydro': HYDRO_COST_PER_WATT,
        'biomass': BIOMASS_COST_PER_WATT,
        'geothermal': GEOTHERMAL_COST_PER_WATT,
        'hybrid': (SOLAR_PANEL_COST_PER_WATT + WIND_TURBINE_COST_PER_WATT) / 2
    }
    
    # Calculate system capacity (kW)
    capacity_factors = {
        'solar': 0.25,
        'wind': 0.35,
        'hydro': 0.45,
        'biomass': 0.70,
        'geothermal': 0.90,
        'hybrid': 0.30
    }
    
    capacity_kw = yearly_kwh / (8760 * capacity_factors[system_type])
    
    # CAPEX calculation
    system_cost = capacity_kw * 1000 * system_costs[system_type]  # Convert to watts
    battery_cost = power_output['daily'] * 1.5 * BATTERY_COST_PER_KWH  # 1.5 days storage
    inverter_cost = capacity_kw * 1000 * INVERTER_COST_PER_WATT
    installation_cost = (system_cost + battery_cost + inverter_cost) * 0.15  # 15% installation
    
    total_capex = system_cost + battery_cost + inverter_cost + installation_cost
    
    # OPEX calculation (annual)
    annual_opex = total_capex * MAINTENANCE_COST_PERCENT
    
    # Revenue calculation
    annual_revenue = yearly_kwh * ELECTRICITY_RATE
    
    # Financial metrics
    net_annual_benefit = annual_revenue - annual_opex
    payback_years = total_capex / net_annual_benefit if net_annual_benefit > 0 else float('inf')
    roi_percent = (net_annual_benefit / total_capex) * 100 if total_capex > 0 else 0
    lcoe = (total_capex + (annual_opex * 25)) / (yearly_kwh * 25)  # 25-year lifetime
    
    return {
        'capex': round(total_capex, 2),
        'opex_annual': round(annual_opex, 2),
        'annual_revenue': round(annual_revenue, 2),
        'payback_years': round(payback_years, 1),
        'roi_percent': round(roi_percent, 1),
        'lcoe': round(lcoe, 3),
        'capacity_kw': round(capacity_kw, 2),
        'net_annual_benefit': round(net_annual_benefit, 2)
    }

def calculate_hybrid_system(data, solar_weight=0.7, wind_weight=0.3):
    """Calculate hybrid system with weighted combination"""
    solar_data = calculate_solar_output(data)
    wind_data = calculate_wind_power(data)
    
    # Weighted combination
    hybrid_daily = (solar_data['daily'] * solar_weight + 
                   wind_data['daily'] * wind_weight)
    
    # Combine monthly breakdowns
    hybrid_monthly = {}
    for month in solar_data['monthly_breakdown'].keys():
        hybrid_monthly[month] = (
            solar_data['monthly_breakdown'][month] * solar_weight +
            wind_data['monthly_breakdown'][month] * wind_weight
        )
    
    hybrid_yearly = sum(hybrid_monthly.values())
    hybrid_monthly_avg = hybrid_yearly / 12
    
    return {
        'daily': hybrid_daily,
        'monthly': hybrid_monthly_avg,
        'yearly': hybrid_yearly,
        'monthly_breakdown': hybrid_monthly,
        'solar_contribution': solar_weight,
        'wind_contribution': wind_weight
    }

def get_ai_recommendation(climate_data, budget=None):
    """AI-assisted system recommendation based on climate data"""
    solar_irradiance = climate_data['ALLSKY_SFC_SW_DWN']['ANN']
    wind_speed = climate_data['WS10M']['ANN']
    temperature = climate_data['T2M']['ANN']
    precipitation = climate_data['PRECTOTCORR']['ANN']
    
    # Score each system based on climate conditions
    scores = {
        'solar': 0,
        'wind': 0,
        'hydro': 0,
        'biomass': 0,
        'geothermal': 0,
        'hybrid': 0
    }
    
    # Solar scoring
    if solar_irradiance > 4.5:
        scores['solar'] += 30
    elif solar_irradiance > 3.5:
        scores['solar'] += 20
    else:
        scores['solar'] += 10
    
    # Wind scoring
    if wind_speed > 6:
        scores['wind'] += 30
    elif wind_speed > 4:
        scores['wind'] += 20
    else:
        scores['wind'] += 10
    
    # Hydro scoring
    if precipitation > 1500:
        scores['hydro'] += 30
    elif precipitation > 1000:
        scores['hydro'] += 20
    else:
        scores['hydro'] += 5
    
    # Biomass scoring
    if temperature > 15 and precipitation > 800:
        scores['biomass'] += 25
    else:
        scores['biomass'] += 10
    
    # Geothermal scoring (assume good everywhere)
    scores['geothermal'] += 20
    
    # Hybrid scoring (combination of solar and wind)
    scores['hybrid'] = (scores['solar'] + scores['wind']) / 2
    
    # Find best system
    best_system = max(scores, key=scores.get)
    
    return {
        'recommended_system': best_system,
        'scores': scores,
        'reasoning': f"Based on climate data: Solar irradiance {solar_irradiance:.1f} kWh/m²/day, "
                    f"Wind speed {wind_speed:.1f} m/s, Temperature {temperature:.1f}°C"
    }

# Enhanced calculation functions with improved accuracy
def calculate_solar_output(data, area=SOLAR_PANEL_AREA):
    """Enhanced solar calculation with temperature effects"""
    irradiance = data['ALLSKY_SFC_SW_DWN']['ANN']
    temperature = data['T2M']['ANN']
    
    # Temperature coefficient for solar panels
    temp_coefficient = -0.004
    temp_factor = 1 + temp_coefficient * (temperature - 25)
    
    # Calculate base daily output
    daily_output = irradiance * area * SOLAR_EFFICIENCY * PERFORMANCE_RATIO * temp_factor
    
    # Monthly variation factors
    monthly_factors = {
        'JAN': 0.7, 'FEB': 0.8, 'MAR': 0.9, 'APR': 1.1,
        'MAY': 1.2, 'JUN': 1.3, 'JUL': 1.3, 'AUG': 1.2,
        'SEP': 1.1, 'OCT': 0.9, 'NOV': 0.8, 'DEC': 0.7
    }
    
    monthly_outputs = {month: daily_output * factor * 30.44 
                      for month, factor in monthly_factors.items()}
    
    return {
        'daily': daily_output,
        'monthly': sum(monthly_outputs.values()) / 12,
        'yearly': sum(monthly_outputs.values()),
        'monthly_breakdown': monthly_outputs
    }

def calculate_wind_power(data):
    """Enhanced wind calculation with Weibull distribution"""
    wind_speed = data['WS10M']['ANN']
    air_temp = data['T2M']['ANN']
    pressure = data['PS']['ANN']
    
    # Adjust air density for temperature and pressure
    air_density = (pressure * 100) / (287.05 * (air_temp + 273.15))
    
    # Weibull parameters
    k = 2.0
    c = wind_speed * 1.128
    
    area = math.pi * WIND_TURBINE_RADIUS ** 2
    
    def weibull_power(v):
        return 0.5 * air_density * area * v**3 * CP * \
               (k/(c**k)) * (v**(k-1)) * math.exp(-(v/c)**k)
    
    power = sum(weibull_power(v) for v in range(3, 26))
    daily_output = power * 24 / 1000
    
    monthly_factors = {
        'JAN': 1.2, 'FEB': 1.1, 'MAR': 1.1, 'APR': 0.9,
        'MAY': 0.8, 'JUN': 0.7, 'JUL': 0.7, 'AUG': 0.8,
        'SEP': 0.9, 'OCT': 1.0, 'NOV': 1.1, 'DEC': 1.2
    }
    
    monthly_outputs = {month: daily_output * factor * 30.44 
                      for month, factor in monthly_factors.items()}
    
    return {
        'daily': daily_output,
        'monthly': sum(monthly_outputs.values()) / 12,
        'yearly': sum(monthly_outputs.values()),
        'monthly_breakdown': monthly_outputs
    }

def calculate_hydro_power(data, head_height=10, flow_rate=1):
    """Enhanced hydro calculation"""
    precipitation = data['PRECTOTCORR']['ANN']
    
    base_flow = flow_rate * (precipitation / 1000)
    base_power = HYDRO_EFFICIENCY * WATER_DENSITY * GRAVITY * head_height * base_flow
    daily_output = base_power * 24 / 1000
    
    monthly_factors = {
        'JAN': 1.2, 'FEB': 1.3, 'MAR': 1.4, 'APR': 1.3,
        'MAY': 1.1, 'JUN': 0.8, 'JUL': 0.6, 'AUG': 0.5,
        'SEP': 0.7, 'OCT': 0.9, 'NOV': 1.0, 'DEC': 1.2
    }
    
    monthly_outputs = {month: daily_output * factor * 30.44 
                      for month, factor in monthly_factors.items()}
    
    return {
        'daily': daily_output,
        'monthly': sum(monthly_outputs.values()) / 12,
        'yearly': sum(monthly_outputs.values()),
        'monthly_breakdown': monthly_outputs
    }

def calculate_biomass_power(data):
    """Enhanced biomass calculation"""
    temp = data['T2M']['ANN']
    humidity = data['RH2M']['ANN']
    precipitation = data['PRECTOTCORR']['ANN']
    
    base_power = 100
    temp_factor = 1 + (temp - 20) * 0.02
    humidity_factor = 1 - (humidity - 50) * 0.005
    growth_factor = min(1.5, max(0.5, precipitation / 1000))
    
    daily_output = base_power * temp_factor * humidity_factor * growth_factor * BIOMASS_EFFICIENCY * 24
    
    monthly_factors = {
        'JAN': 0.7, 'FEB': 0.7, 'MAR': 0.8, 'APR': 1.0,
        'MAY': 1.2, 'JUN': 1.3, 'JUL': 1.3, 'AUG': 1.2,
        'SEP': 1.1, 'OCT': 0.9, 'NOV': 0.8, 'DEC': 0.7
    }
    
    monthly_outputs = {month: daily_output * factor * 30.44 
                      for month, factor in monthly_factors.items()}
    
    return {
        'daily': daily_output,
        'monthly': sum(monthly_outputs.values()) / 12,
        'yearly': sum(monthly_outputs.values()),
        'monthly_breakdown': monthly_outputs
    }

def calculate_geothermal_power(data):
    """Enhanced geothermal calculation"""
    temp = data['T2M']['ANN']
    pressure = data['PS']['ANN']
    
    base_power = 200
    depth = 2000
    bottom_temp = temp + (depth * 0.025)
    temp_gradient = (bottom_temp - temp) / depth
    
    temp_factor = 1 + (temp_gradient - 0.025) * 10
    pressure_factor = pressure / 1013.25
    
    daily_output = base_power * temp_factor * pressure_factor * GEOTHERMAL_EFFICIENCY * 24
    
    monthly_outputs = {month: daily_output for month in [
        'JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
        'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'
    ]}
    
    return {
        'daily': daily_output,
        'monthly': daily_output * 30.44,
        'yearly': daily_output * 365.25,
        'monthly_breakdown': monthly_outputs
    }

def calculate_environmental_impact(yearly_output):
    """Enhanced environmental impact calculation"""
    co2_saved = yearly_output * CO2_SAVED_PER_KWH
    trees_equivalent = int(co2_saved / 1000 * TREES_PER_TON_CO2)
    
    # Additional environmental metrics
    land_area_needed = yearly_output / 1000  # m² per MWh
    water_saved = yearly_output * 0.5  # liters per kWh
    
    return {
        'co2_saved': co2_saved,
        'trees_equivalent': trees_equivalent,
        'land_area_needed': land_area_needed,
        'water_saved': water_saved
    }

def get_recommended_equipment(system_type, power_output, financial_data):
    """Enhanced equipment recommendations with financial data"""
    equipment = []
    yearly_kwh = power_output['yearly']
    capacity_kw = financial_data['capacity_kw']
    
    if system_type in ['solar', 'hybrid']:
        num_panels = max(1, int(capacity_kw * 1000 / 400))  # 400W panels
        equipment.append({
            'name': f'Solar Panel Array',
            'specs': f'{num_panels} x 400W Monocrystalline Panels',
            'cost': num_panels * 400 * SOLAR_PANEL_COST_PER_WATT
        })
        equipment.append({
            'name': 'Solar Inverter',
            'specs': f'{capacity_kw:.1f}kW Grid-Tied Inverter',
            'cost': capacity_kw * 1000 * INVERTER_COST_PER_WATT
        })
        
    if system_type in ['wind', 'hybrid']:
        equipment.append({
            'name': 'Wind Turbine',
            'specs': f'{capacity_kw:.1f}kW Rated Power',
            'cost': capacity_kw * 1000 * WIND_TURBINE_COST_PER_WATT
        })
        
    if system_type == 'hydro':
        equipment.append({
            'name': 'Micro Hydro Turbine',
            'specs': f'{capacity_kw:.1f}kW Pelton Wheel',
            'cost': capacity_kw * 1000 * HYDRO_COST_PER_WATT
        })
        
    if system_type == 'biomass':
        equipment.append({
            'name': 'Biomass Boiler',
            'specs': f'{capacity_kw:.1f}kW Thermal',
            'cost': capacity_kw * 1000 * BIOMASS_COST_PER_WATT
        })
        
    if system_type == 'geothermal':
        equipment.append({
            'name': 'Ground Source Heat Pump',
            'specs': f'{capacity_kw:.1f}kW Heat Pump',
            'cost': capacity_kw * 1000 * GEOTHERMAL_COST_PER_WATT
        })
    
    # Common equipment
    battery_size = max(5, power_output['daily'] * 1.5)
    equipment.append({
        'name': 'Battery Storage',
        'specs': f'{battery_size:.1f}kWh Lithium-ion Battery',
        'cost': battery_size * BATTERY_COST_PER_KWH
    })
    
    equipment.append({
        'name': 'Smart Energy Monitor',
        'specs': 'Real-time Monitoring & Control System',
        'cost': 500
    })
    
    return equipment

@csrf_exempt
@require_http_methods(["POST"])
def assess_location(request):
    """Enhanced assessment endpoint with comprehensive data"""
    try:
        data = json.loads(request.body)
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        system_type = data.get('system_type')
        location_name = data.get('location_name', 'Unknown Location')

        if not all([latitude, longitude, system_type]):
            return JsonResponse({
                'error': 'Missing required parameters'
            }, status=400)

        # Get climate data with caching
        try:
            climate_data = get_nasa_power_data(latitude, longitude)
        except Exception as e:
            return JsonResponse({'error': f'Climate data error: {str(e)}'}, status=500)
        
        # Calculate power output
        calculators = {
            'solar': calculate_solar_output,
            'wind': calculate_wind_power,
            'hydro': calculate_hydro_power,
            'biomass': calculate_biomass_power,
            'geothermal': calculate_geothermal_power,
            'hybrid': calculate_hybrid_system
        }
        
        if system_type not in calculators:
            return JsonResponse({'error': 'Invalid system type'}, status=400)
        
        try:
            # Calculate power output
            power_output = calculators[system_type](climate_data)
            
            # Calculate environmental impact
            environmental_impact = calculate_environmental_impact(power_output['yearly'])
            
            # Calculate financial metrics
            financial_data = calculate_financial_metrics(system_type, power_output, {
                'latitude': latitude,
                'longitude': longitude
            })
            
            # Get AI recommendation
            ai_recommendation = get_ai_recommendation(climate_data)
            
            # Get recommended equipment
            equipment = get_recommended_equipment(system_type, power_output, financial_data)
            
            # Generate assessment ID
            assessment_id = str(uuid.uuid4())
            
            response_data = {
                'assessment_id': assessment_id,
                'system_type': system_type,
                'location': {
                    'name': location_name,
                    'latitude': latitude,
                    'longitude': longitude
                },
                'climate_data': {
                    'solar_irradiance': climate_data['ALLSKY_SFC_SW_DWN']['ANN'],
                    'wind_speed': climate_data['WS10M']['ANN'],
                    'temperature': climate_data['T2M']['ANN'],
                    'humidity': climate_data['RH2M']['ANN'],
                    'precipitation': climate_data['PRECTOTCORR']['ANN']
                },
                'power_output': power_output,
                'environmental_impact': environmental_impact,
                'financial_metrics': financial_data,
                'recommended_equipment': equipment,
                'ai_recommendation': ai_recommendation,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            return JsonResponse(response_data)
            
        except Exception as calc_error:
            return JsonResponse({'error': f'Calculation error: {str(calc_error)}'}, status=500)
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except Exception as e:
        return JsonResponse({'error': f'Unexpected error: {str(e)}'}, status=500)

@csrf_exempt
def get_assessment(request, assessment_id):
    """Retrieve a saved assessment"""
    try:
        assessment = Assessment.objects.get(id=assessment_id)
        result = Result.objects.get(assessment=assessment)
        
        # Parse the recommended equipment JSON
        recommended_equipment = json.loads(result.recommended_equipment)
        if isinstance(recommended_equipment, list):
            equipment_list = recommended_equipment
        else:
            equipment_list = recommended_equipment.get('equipment', [])
        
        response_data = {
            'assessment_id': assessment.id,
            'location': {
                'name': assessment.location_name,
                'latitude': assessment.latitude,
                'longitude': assessment.longitude
            },
            'system_type': assessment.system_type.replace('_', ' ').title(),
            'optimal_setup': {
                'tilt_angle': result.optimal_tilt,
                'orientation': result.optimal_orientation
            },
            'power_output': {
                'daily': result.daily_output,
                'monthly': result.monthly_output,
                'yearly': result.yearly_output
            },
            'environmental_impact': {
                'co2_saved': result.co2_saved,
                'trees_equivalent': result.trees_equivalent
            },
            'recommended_equipment': equipment_list,
            'created_at': assessment.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # If format=pdf is requested, generate and serve PDF
        if request.GET.get('format') == 'pdf':
            try:
                # Create PDF buffer
                buffer = io.BytesIO()
                
                # Create the PDF document
                doc = SimpleDocTemplate(
                    buffer,
                    pagesize=A4,
                    rightMargin=72,
                    leftMargin=72,
                    topMargin=72,
                    bottomMargin=72
                )
                
                # Container for the 'Flowable' objects
                elements = []
                
                # Get styles
                styles = getSampleStyleSheet()
                title_style = ParagraphStyle(
                    'CustomTitle',
                    parent=styles['Heading1'],
                    fontSize=24,
                    spaceAfter=30,
                    alignment=1  # Center alignment
                )
                
                heading_style = ParagraphStyle(
                    'CustomHeading',
                    parent=styles['Heading2'],
                    fontSize=16,
                    spaceAfter=12,
                    textColor=colors.HexColor('#0f9d58')
                )
                
                # Add title
                elements.append(Paragraph("Renewable Energy Assessment Report", title_style))
                elements.append(Spacer(1, 12))
                
                # Location Details
                elements.append(Paragraph("Location Details", heading_style))
                location_data = [
                    ["Location Name:", response_data['location']['name']],
                    ["Coordinates:", f"{response_data['location']['latitude']}°, {response_data['location']['longitude']}°"],
                    ["System Type:", response_data['system_type']]
                ]
                location_table = Table(location_data, colWidths=[2*inch, 4*inch])
                location_table.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                    ('PADDING', (0, 0), (-1, -1), 6),
                ]))
                elements.append(location_table)
                elements.append(Spacer(1, 20))
                
                # Optimal Setup
                elements.append(Paragraph("Optimal Setup Configuration", heading_style))
                setup_data = [
                    ["Optimal Tilt Angle:", f"{response_data['optimal_setup']['tilt_angle']:.1f}°"],
                    ["Optimal Orientation:", f"{response_data['optimal_setup']['orientation']:.1f}°"]
                ]
                setup_table = Table(setup_data, colWidths=[2*inch, 4*inch])
                setup_table.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                    ('PADDING', (0, 0), (-1, -1), 6),
                ]))
                elements.append(setup_table)
                elements.append(Spacer(1, 20))
                
                # Power Output
                elements.append(Paragraph("Power Output Estimates", heading_style))
                power_data = [
                    ["Daily Average:", f"{response_data['power_output']['daily']:.1f} kWh"],
                    ["Monthly Average:", f"{response_data['power_output']['monthly']:.0f} kWh"],
                    ["Yearly Total:", f"{response_data['power_output']['yearly']:.0f} kWh"]
                ]
                power_table = Table(power_data, colWidths=[2*inch, 4*inch])
                power_table.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                    ('PADDING', (0, 0), (-1, -1), 6),
                ]))
                elements.append(power_table)
                elements.append(Spacer(1, 20))
                
                # Environmental Impact
                elements.append(Paragraph("Environmental Impact", heading_style))
                impact_data = [
                    ["CO₂ Savings:", f"{response_data['environmental_impact']['co2_saved']:.0f} kg/year"],
                    ["Trees Equivalent:", f"{response_data['environmental_impact']['trees_equivalent']} trees"]
                ]
                impact_table = Table(impact_data, colWidths=[2*inch, 4*inch])
                impact_table.setStyle(TableStyle([
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#e6f4ea')),
                    ('PADDING', (0, 0), (-1, -1), 6),
                ]))
                elements.append(impact_table)
                elements.append(Spacer(1, 20))
                
                # Recommended Equipment
                elements.append(Paragraph("Recommended Equipment", heading_style))
                equipment_items = [[item] for item in response_data['recommended_equipment']]
                if equipment_items:
                    equipment_table = Table(equipment_items, colWidths=[6*inch])
                    equipment_table.setStyle(TableStyle([
                        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                        ('PADDING', (0, 0), (-1, -1), 6),
                    ]))
                    elements.append(equipment_table)
                
                # Footer
                elements.append(Spacer(1, 30))
                footer_style = ParagraphStyle(
                    'Footer',
                    parent=styles['Normal'],
                    fontSize=8,
                    textColor=colors.grey,
                    alignment=1
                )
                elements.append(Paragraph(
                    f"Report generated on: {response_data['created_at']}<br/>"
                    f"Assessment ID: {response_data['assessment_id']}",
                    footer_style
                ))
                
                # Build PDF document
                doc.build(elements)
                
                # Get the value of the BytesIO buffer and write it to the response
                pdf = buffer.getvalue()
                buffer.close()
                
                # Generate response
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"renewable_energy_assessment_{timestamp}.pdf"
                
                response = HttpResponse(content_type='application/pdf')
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                response.write(pdf)
                
                return response
                
            except Exception as e:
                print(f"PDF generation failed: {str(e)}")
                # Fallback to HTML if PDF generation fails
                html_content = render_to_string('assessment_results.html', response_data)
                return HttpResponse(html_content, content_type='text/html')
        
        return JsonResponse(response_data)
        
    except (Assessment.DoesNotExist, Result.DoesNotExist):
        return JsonResponse({'error': 'Assessment not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@csrf_exempt
@require_http_methods(["POST"])
def generate_pdf(request):
    try:
        data = json.loads(request.body)
        
        # Ensure location data exists
        if 'location' not in data:
            return JsonResponse({
                'error': 'Missing location data'
            }, status=400)

        # Create PDF with location name
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )
        
        elements = []
        styles = getSampleStyleSheet()
        
        # Title with primary color
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=30,
            textColor=colors.HexColor('#003049')
        )
        elements.append(Paragraph("Renewable Energy Assessment Report", title_style))
        
        # Date with accent color
        date_style = ParagraphStyle(
            'DateStyle',
            parent=styles['Normal'],
            fontSize=12,
            textColor=colors.HexColor('#f77f00')
        )
        elements.append(Paragraph(f"Generated on: {datetime.now().strftime('%B %d, %Y')}", date_style))
        elements.append(Spacer(1, 20))
        
        # Location section
        elements.append(Paragraph("Location Details", styles['Heading2']))
        location_data = [
            ["Location Name:", data['location'].get('name', 'Unknown Location')],
            ["Latitude:", f"{data['location']['latitude']:.6f}°"],
            ["Longitude:", f"{data['location']['longitude']:.6f}°"]
        ]
        
        # Table with new color scheme
        location_table = Table(location_data, colWidths=[2*inch, 4*inch])
        location_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#eae2b7')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#003049')),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#fcbf49'))
        ]))
        elements.append(location_table)
        elements.append(Spacer(1, 20))
        
        # System Information
        elements.append(Paragraph("System Configuration", styles['Heading2']))
        system_data = [
            ["System Type:", data['system_type']],
            ["Optimal Tilt Angle:", f"{data['optimal_setup']['tilt_angle']}°"],
            ["Optimal Orientation:", f"{data['optimal_setup']['orientation']}°"]
        ]
        system_table = Table(system_data, colWidths=[2*inch, 4*inch])
        system_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(system_table)
        elements.append(Spacer(1, 20))
        
        # Power Output
        elements.append(Paragraph("Power Output", styles['Heading2']))
        power_data = [
            ["Daily Production:", f"{data['power_output']['daily']:.1f} kWh"],
            ["Monthly Production:", f"{data['power_output']['monthly']:.1f} kWh"],
            ["Yearly Production:", f"{data['power_output']['yearly']:.1f} kWh"]
        ]
        power_table = Table(power_data, colWidths=[2*inch, 4*inch])
        power_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(power_table)
        elements.append(Spacer(1, 20))
        
        # Environmental Impact
        elements.append(Paragraph("Environmental Impact", styles['Heading2']))
        impact_data = [
            ["CO₂ Saved:", f"{data['environmental_impact']['co2_saved']:.1f} kg/year"],
            ["Trees Equivalent:", f"{data['environmental_impact']['trees_equivalent']} trees"]
        ]
        impact_table = Table(impact_data, colWidths=[2*inch, 4*inch])
        impact_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(impact_table)
        elements.append(Spacer(1, 20))
        
        # Recommended Equipment
        elements.append(Paragraph("Recommended Equipment", styles['Heading2']))
        for item in data['recommended_equipment']:
            elements.append(Paragraph(f"• {item}", styles['Normal']))
            elements.append(Spacer(1, 6))
        
        # Build PDF
        doc.build(elements)
        
        # Get the value of the BytesIO buffer and write response
        pdf = buffer.getvalue()
        buffer.close()
        
        # Create the HTTP response with PDF content
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="renewable_energy_assessment.pdf"'
        response.write(pdf)
        
        return response
        
    except Exception as e:
        return JsonResponse({
            'error': str(e)
        }, status=500)

# -----------------------------
# Utility Functions
# -----------------------------
def get_user_location():
    try:
        response = requests.get("https://ipinfo.io/json", timeout=5)
        if response.status_code != 200:
            return None, None
        data = response.json()
        loc = data["loc"].split(",")
        lat = float(loc[0])
        lon = float(loc[1])
        return lat, lon
    except Exception as e:
        print("Location error:", e)
        return None, None

def recommend_tilt_angle(lat):
    return {
        "Winter": lat + 15,
        "Summer": lat - 15,
        "Year-Round": lat
    }

def recommend_turbine_orientation(direction):
    return f"{direction}° ±15°"

def co2_savings(kwh):
    return kwh * CO2_SAVED_PER_KWH

def get_location_name(lat, lon):
    """Get location name from coordinates using OpenCage Geocoding API"""
    try:
        # URL encode the coordinates
        coords = urllib.parse.quote(f"{lat},{lon}")
        url = f"https://api.opencagedata.com/geocode/v1/json?q={coords}&key={OPENCAGE_API_KEY}"
        
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data['results']:
            # Get the first result
            result = data['results'][0]
            components = result['components']
            
            # Try to construct a meaningful location name
            location_parts = []
            
            # Add city/town/village if available
            if components.get('city'):
                location_parts.append(components['city'])
            elif components.get('town'):
                location_parts.append(components['town'])
            elif components.get('village'):
                location_parts.append(components['village'])
            
            # Add state/province if available
            if components.get('state'):
                location_parts.append(components['state'])
            
            # Add country
            if components.get('country'):
                location_parts.append(components['country'])
            
            # Join all parts with commas
            location_name = ', '.join(location_parts)
            
            return location_name if location_name else 'Unknown Location'
    except Exception as e:
        print(f"Geocoding error: {e}")
        return 'Unknown Location'




