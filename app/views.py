from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from .models import Assessment, Result
import requests
import math
import json
from datetime import datetime
from django.template.loader import render_to_string
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
import io
import urllib.parse

OPENCAGE_API_KEY = 'fd8f381a99404d03857ca7b46f35b865'

def index(request):
    return render(request, 'index.html')

# -----------------------------
# Constants
# -----------------------------
SOLAR_EFFICIENCY = 0.20
PERFORMANCE_RATIO = 0.75
SOLAR_PANEL_AREA = 1.6
AIR_DENSITY = 1.225
WIND_TURBINE_RADIUS = 1.5
CP = 0.4
CO2_SAVED_PER_KWH = 0.42
WATER_DENSITY = 1000  # kg/m³
GRAVITY = 9.81  # m/s²
HYDRO_EFFICIENCY = 0.9
BIOMASS_EFFICIENCY = 0.25
GEOTHERMAL_EFFICIENCY = 0.15
TREES_PER_TON_CO2 = 45

# -----------------------------
# NASA POWER API Functions
# -----------------------------
def get_nasa_power_data(lat, lon):
    """Fetch comprehensive climate data from NASA POWER API"""
    parameters = [
        'T2M',          # Temperature at 2 meters
        'RH2M',         # Relative Humidity
        'PRECTOTCORR',  # Precipitation
        'WS10M',        # Wind Speed at 10 meters
        'WD10M',        # Wind Direction
        'PS',           # Surface Pressure
        'ALLSKY_SFC_SW_DWN',  # Solar Irradiance
        'CLRSKY_SFC_SW_DWN',  # Clear Sky Irradiance
        'TOA_SW_DWN',   # Top of Atmosphere Solar
        'QV2M',         # Specific Humidity
        'TQV'           # Total Column Water Vapor
    ]
    
    url = (
        f"https://power.larc.nasa.gov/api/temporal/climatology/point"
        f"?parameters={','.join(parameters)}"
        f"&community=RE&longitude={lon}&latitude={lat}&format=JSON"
    )
    
    try:
        response = requests.get(url, timeout=30)  # Increased timeout
        response.raise_for_status()
        data = response.json()
        
        if 'properties' not in data or 'parameter' not in data['properties']:
            raise ValueError("Invalid response format from NASA POWER API")
            
        return data['properties']['parameter']
        
    except requests.Timeout:
        raise Exception("NASA POWER API request timed out. Please try again.")
    except requests.RequestException as e:
        raise Exception(f"Failed to fetch data from NASA POWER API: {str(e)}")
    except (KeyError, ValueError) as e:
        raise Exception(f"Invalid data received from NASA POWER API: {str(e)}")
    except Exception as e:
        raise Exception(f"Unexpected error while fetching NASA POWER data: {str(e)}")

# -----------------------------
# Calculation Functions
# -----------------------------
def calculate_solar_output(data, area=SOLAR_PANEL_AREA):
    """Calculate solar power output with monthly variations"""
    irradiance = data['ALLSKY_SFC_SW_DWN']['ANN']
    temperature = data['T2M']['ANN']
    
    # Temperature coefficient for solar panels (typically -0.4% per degree C above 25°C)
    temp_coefficient = -0.004
    temp_factor = 1 + temp_coefficient * (temperature - 25)
    
    # Calculate base daily output
    daily_output = irradiance * area * SOLAR_EFFICIENCY * PERFORMANCE_RATIO * temp_factor
    
    # Monthly variation factors (approximate based on latitude)
    monthly_factors = {
        'JAN': 0.7, 'FEB': 0.8, 'MAR': 0.9, 'APR': 1.1,
        'MAY': 1.2, 'JUN': 1.3, 'JUL': 1.3, 'AUG': 1.2,
        'SEP': 1.1, 'OCT': 0.9, 'NOV': 0.8, 'DEC': 0.7
    }
    
    # Calculate monthly outputs
    monthly_outputs = {month: daily_output * factor * 30.44 
                      for month, factor in monthly_factors.items()}
    
    return {
        'daily': daily_output,
        'monthly': sum(monthly_outputs.values()) / 12,
        'yearly': sum(monthly_outputs.values()),
        'monthly_breakdown': monthly_outputs
    }

def calculate_wind_power(data):
    """Calculate wind power output with Weibull distribution"""
    wind_speed = data['WS10M']['ANN']
    air_temp = data['T2M']['ANN']
    pressure = data['PS']['ANN']
    
    # Adjust air density for temperature and pressure
    air_density = (pressure * 100) / (287.05 * (air_temp + 273.15))
    
    # Weibull parameters (typical values)
    k = 2.0  # shape parameter
    c = wind_speed * 1.128  # scale parameter
    
    area = math.pi * WIND_TURBINE_RADIUS ** 2
    
    # Calculate power using Weibull distribution
    def weibull_power(v):
        return 0.5 * air_density * area * v**3 * CP * \
               (k/(c**k)) * (v**(k-1)) * math.exp(-(v/c)**k)
    
    # Integrate over wind speeds from 3 to 25 m/s
    power = sum(weibull_power(v) for v in range(3, 26))
    daily_output = power * 24 / 1000  # Convert to kWh
    
    # Monthly variation factors
    monthly_factors = {
        'JAN': 1.2, 'FEB': 1.1, 'MAR': 1.1, 'APR': 0.9,
        'MAY': 0.8, 'JUN': 0.7, 'JUL': 0.7, 'AUG': 0.8,
        'SEP': 0.9, 'OCT': 1.0, 'NOV': 1.1, 'DEC': 1.2
    }
    
    # Calculate monthly outputs
    monthly_outputs = {month: daily_output * factor * 30.44 
                      for month, factor in monthly_factors.items()}
    
    return {
        'daily': daily_output,
        'monthly': sum(monthly_outputs.values()) / 12,
        'yearly': sum(monthly_outputs.values()),
        'monthly_breakdown': monthly_outputs
    }

def calculate_hydro_power(data, head_height=10, flow_rate=1):
    """Calculate hydroelectric power output with seasonal variations"""
    precipitation = data['PRECTOTCORR']['ANN']
    
    # Adjust flow rate based on precipitation
    base_flow = flow_rate * (precipitation / 1000)  # Convert mm to m
    
    # Calculate base power
    base_power = HYDRO_EFFICIENCY * WATER_DENSITY * GRAVITY * head_height * base_flow
    daily_output = base_power * 24 / 1000  # Convert to kWh
    
    # Monthly variation factors based on precipitation patterns
    monthly_factors = {
        'JAN': 1.2, 'FEB': 1.3, 'MAR': 1.4, 'APR': 1.3,
        'MAY': 1.1, 'JUN': 0.8, 'JUL': 0.6, 'AUG': 0.5,
        'SEP': 0.7, 'OCT': 0.9, 'NOV': 1.0, 'DEC': 1.2
    }
    
    # Calculate monthly outputs
    monthly_outputs = {month: daily_output * factor * 30.44 
                      for month, factor in monthly_factors.items()}
    
    return {
        'daily': daily_output,
        'monthly': sum(monthly_outputs.values()) / 12,
        'yearly': sum(monthly_outputs.values()),
        'monthly_breakdown': monthly_outputs
    }

def calculate_biomass_power(data):
    """Calculate biomass power output based on temperature and humidity"""
    temp = data['T2M']['ANN']
    humidity = data['RH2M']['ANN']
    precipitation = data['PRECTOTCORR']['ANN']
    
    # Base power calculation
    base_power = 100  # Base power potential in kW
    
    # Environmental factors
    temp_factor = 1 + (temp - 20) * 0.02  # Temperature adjustment
    humidity_factor = 1 - (humidity - 50) * 0.005  # Humidity adjustment
    growth_factor = min(1.5, max(0.5, precipitation / 1000))  # Precipitation impact
    
    daily_output = base_power * temp_factor * humidity_factor * growth_factor * BIOMASS_EFFICIENCY * 24
    
    # Monthly variation factors based on growing seasons
    monthly_factors = {
        'JAN': 0.7, 'FEB': 0.7, 'MAR': 0.8, 'APR': 1.0,
        'MAY': 1.2, 'JUN': 1.3, 'JUL': 1.3, 'AUG': 1.2,
        'SEP': 1.1, 'OCT': 0.9, 'NOV': 0.8, 'DEC': 0.7
    }
    
    # Calculate monthly outputs
    monthly_outputs = {month: daily_output * factor * 30.44 
                      for month, factor in monthly_factors.items()}
    
    return {
        'daily': daily_output,
        'monthly': sum(monthly_outputs.values()) / 12,
        'yearly': sum(monthly_outputs.values()),
        'monthly_breakdown': monthly_outputs
    }

def calculate_geothermal_power(data):
    """Calculate geothermal power output"""
    temp = data['T2M']['ANN']
    pressure = data['PS']['ANN']
    
    # Base power calculation
    base_power = 200  # Base power potential in kW
    
    # Temperature gradient factor (assumes 25°C/km)
    depth = 2000  # meters
    bottom_temp = temp + (depth * 0.025)  # Temperature at depth
    temp_gradient = (bottom_temp - temp) / depth
    
    # Efficiency factors
    temp_factor = 1 + (temp_gradient - 0.025) * 10  # Gradient efficiency
    pressure_factor = pressure / 1013.25  # Pressure efficiency
    
    daily_output = base_power * temp_factor * pressure_factor * GEOTHERMAL_EFFICIENCY * 24
    
    # Geothermal is relatively constant throughout the year
    monthly_outputs = {
        'JAN': daily_output, 'FEB': daily_output, 'MAR': daily_output,
        'APR': daily_output, 'MAY': daily_output, 'JUN': daily_output,
        'JUL': daily_output, 'AUG': daily_output, 'SEP': daily_output,
        'OCT': daily_output, 'NOV': daily_output, 'DEC': daily_output
    }
    
    return {
        'daily': daily_output,
        'monthly': daily_output * 30.44,
        'yearly': daily_output * 365.25,
        'monthly_breakdown': monthly_outputs
    }

def calculate_hybrid_power(data):
    """Calculate hybrid system power output (solar + wind)"""
    solar = calculate_solar_output(data)
    wind = calculate_wind_power(data)
    
    # Combine monthly breakdowns
    monthly_outputs = {
        month: solar['monthly_breakdown'][month] + wind['monthly_breakdown'][month]
        for month in solar['monthly_breakdown'].keys()
    }
    
    return {
        'daily': solar['daily'] + wind['daily'],
        'monthly': sum(monthly_outputs.values()) / 12,
        'yearly': sum(monthly_outputs.values()),
        'monthly_breakdown': monthly_outputs
    }

def calculate_environmental_impact(yearly_output):
    """Calculate CO2 savings and equivalent trees"""
    co2_saved = yearly_output * CO2_SAVED_PER_KWH
    trees_equivalent = int(co2_saved / 1000 * TREES_PER_TON_CO2)
    return {
        'co2_saved': co2_saved,
        'trees_equivalent': trees_equivalent
    }

def get_recommended_equipment(system_type, power_output):
    """Generate equipment recommendations based on system type and power output"""
    equipment = []
    yearly_kwh = power_output['yearly']
    
    if system_type in ['solar', 'hybrid']:
        num_panels = max(1, int(yearly_kwh / (365 * 5)))  # Assume 5kWh per panel per day
        equipment.append(f"Solar Panel Array - {num_panels} x 400W Panels")
        equipment.append("Solar Inverter - Grid-Tied 5kW")
        
    if system_type in ['wind', 'hybrid']:
        turbine_size = max(1.5, yearly_kwh / (365 * 24 * 0.3))  # Assume 30% capacity factor
        equipment.append(f"Wind Turbine - {turbine_size:.1f}kW Rated Power")
        
    if system_type == 'hydro':
        equipment.append("Micro Hydro Turbine - 2kW")
        equipment.append("Hydro Controller - Advanced Flow Management")
        
    if system_type == 'biomass':
        equipment.append("Biomass Boiler - 10kW Thermal")
        equipment.append("Steam Turbine Generator - 5kW")
        
    if system_type == 'geothermal':
        equipment.append("Ground Source Heat Pump - 8kW")
        equipment.append("Geothermal Heat Exchanger - 200m depth")
    
    # Common equipment for all systems
    battery_size = max(5, power_output['daily'] * 1.5)  # 1.5 days of storage
    equipment.append(f"Battery Storage - {battery_size:.1f}kWh Lithium-ion")
    equipment.append("Smart Energy Monitor & Control System")
    
    return equipment

# -----------------------------
# API Endpoints
# -----------------------------
@csrf_exempt
def assess_location(request):
    """Handle renewable energy assessment requests"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method is allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        lat = float(data.get('latitude'))
        lon = float(data.get('longitude'))
        system_type = data.get('system_type')
        
        # Validate inputs
        if not all([lat, lon, system_type]):
            return JsonResponse({'error': 'Missing required parameters'}, status=400)
        
        # Get climate data
        try:
            climate_data = get_nasa_power_data(lat, lon)
            if not climate_data:
                return JsonResponse({'error': 'Failed to fetch climate data'}, status=500)
        except Exception as e:
            return JsonResponse({'error': f'NASA API error: {str(e)}'}, status=500)
        
        # Calculate power output based on system type
        calculators = {
            'solar': calculate_solar_output,
            'wind': calculate_wind_power,
            'hydro': calculate_hydro_power,
            'biomass': calculate_biomass_power,
            'geothermal': calculate_geothermal_power,
            'hybrid': calculate_hybrid_power
        }
        
        if system_type not in calculators:
            return JsonResponse({'error': 'Invalid system type'}, status=400)
        
        try:
            # Calculate power output
            power_output = calculators[system_type](climate_data)
            
            # Calculate environmental impact
            impact = calculate_environmental_impact(power_output['yearly'])
            
            # Calculate optimal setup
            optimal_setup = {
                'tilt_angle': recommend_tilt_angle(lat)['Year-Round'],
                'orientation': float(recommend_turbine_orientation(climate_data['WD10M']['ANN']).split('°')[0])
                if system_type in ['wind', 'hybrid'] else lat
            }
            
            # Get recommended equipment
            equipment = get_recommended_equipment(system_type, power_output)
            
            # Try to get location name, but don't fail if it doesn't work
            try:
                location_name = get_location_name(lat, lon)
            except:
                location_name = f"Location at {lat:.4f}, {lon:.4f}"
            
            response_data = {
                'location': {
                    'name': location_name,
                    'latitude': lat,
                    'longitude': lon
                },
                'system_type': system_type.replace('_', ' ').title(),
                'optimal_setup': optimal_setup,
                'power_output': power_output,
                'environmental_impact': impact,
                'recommended_equipment': equipment,
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            return JsonResponse(response_data)
            
        except Exception as calc_error:
            return JsonResponse({'error': f'Calculation error: {str(calc_error)}'}, status=500)
            
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON data'}, status=400)
    except ValueError as ve:
        return JsonResponse({'error': f'Value error: {str(ve)}'}, status=400)
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
def generate_pdf(request):
    """Generate PDF report from assessment data"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Only POST method is allowed'}, status=405)
    
    try:
        data = json.loads(request.body)
        
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
            ["Location:", data['location']['name']],
            ["Coordinates:", f"{data['location']['latitude']}°, {data['location']['longitude']}°"],
            ["System Type:", data['system_type']]
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
            ["Optimal Tilt Angle:", f"{data['optimal_setup']['tilt_angle']:.1f}°"],
            ["Optimal Orientation:", f"{data['optimal_setup']['orientation']:.1f}°"]
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
            ["Daily Average:", f"{data['power_output']['daily']:.1f} kWh"],
            ["Monthly Average:", f"{data['power_output']['monthly']:.0f} kWh"],
            ["Yearly Total:", f"{data['power_output']['yearly']:.0f} kWh"]
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
            ["CO₂ Savings:", f"{data['environmental_impact']['co2_saved']:.0f} kg/year"],
            ["Trees Equivalent:", f"{data['environmental_impact']['trees_equivalent']} trees"]
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
        equipment_items = [[item] for item in data['recommended_equipment']]
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
            f"Report generated on: {data['created_at']}",
            footer_style
        ))
        
        # Build PDF document
        doc.build(elements)
        
        # Get the value of the BytesIO buffer and write it to the response
        pdf = buffer.getvalue()
        buffer.close()
        
        # Generate response
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="renewable_energy_assessment_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf"'
        response.write(pdf)
        
        return response
        
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

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




