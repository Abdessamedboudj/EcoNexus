# EcoNexus - Renewable Energy Assessment Platform

EcoNexus is a comprehensive web application that helps users assess and optimize renewable energy solutions for their locations. The platform provides detailed analysis for various renewable energy systems including solar, wind, hydro, biomass, and geothermal power.

## Features

- Multi-source renewable energy assessment
- Location-based climate data analysis
- Detailed power output calculations
- Environmental impact assessment
- Equipment recommendations
- PDF report generation

## Setup

1. Clone the repository:
```bash
git clone https://github.com/Abdessamedboudj/EcoNexus.git
cd EcoNexus
```

2. Create a virtual environment and activate it:
```bash
python -m venv nenv
source nenv/bin/activate  # On Windows use: nenv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a .env file in the root directory with the following variables:
```
SECRET_KEY=your-secret-key-here
OPENCAGE_API_KEY=your-opencage-api-key
DEBUG=True
```

5. Run migrations:
```bash
python manage.py migrate
```
6. Start the development server:
```bash
python manage.py runserver
```

## Environment Variables

- `SECRET_KEY`: Django secret key for security
- `OPENCAGE_API_KEY`: API key for geocoding services
- `DEBUG`: Set to True for development, False for production

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
"# EcoNexus" 
"# EcoNexus" 
