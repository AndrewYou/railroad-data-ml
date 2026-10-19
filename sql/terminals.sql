-- Terminal coordinates for the dashboard map (approximate, city or yard level).
-- Names must match the terminal dwell measure exactly. The service load flags any
-- terminal an active railroad reports that is missing here (check: unmapped_terminal).
INSERT INTO core.terminal (railroad, terminal, lat, lon) VALUES
  ('BNSF', 'Barstow, CA',                 34.90, -117.02),
  ('BNSF', 'Denver, CO',                  39.77, -104.98),
  ('BNSF', 'Fort Worth, TX',              32.98, -97.32),   -- Alliance
  ('BNSF', 'Galesburg, IL',               40.95, -90.37),
  ('BNSF', 'Kansas City, KS',             39.08, -94.66),   -- Argentine
  ('BNSF', 'Lincoln, NE',                 40.81, -96.70),
  ('BNSF', 'Memphis, TN',                 35.02, -89.95),
  ('BNSF', 'Northtown, MN',               45.07, -93.25),
  ('BNSF', 'Pasco, WA',                   46.24, -119.10),
  ('BNSF', 'Tulsa, OK',                   36.15, -95.99),
  ('CN',   'BATON ROUGE',                 30.45, -91.19),
  ('CN',   'CHAMPAIGN',                   40.12, -88.24),
  ('CN',   'FOND DU LAC',                 43.77, -88.45),
  ('CN',   'GEISMAR',                     30.22, -91.01),
  ('CN',   'JACKSON',                     32.33, -90.18),
  ('CN',   'KIRK YARD',                   41.60, -87.35),   -- Gary, IN
  ('CN',   'MARKHAM',                     41.59, -87.66),   -- Homewood, IL
  ('CN',   'MEMPHIS',                     35.08, -90.08),   -- Johnston Yard
  ('CN',   'PROCTOR',                     46.75, -92.23),
  ('CN',   'STEVENS POINT',               44.52, -89.57),
  ('CPKC', 'Bensenville',                 41.96, -87.94),
  ('CPKC', 'Harvey',                      48.01, -99.93),   -- Harvey, ND
  ('CPKC', 'Jackson',                     32.27, -90.22),
  ('CPKC', 'Kansas City',                 39.10, -94.58),   -- Knoche
  ('CPKC', 'Laredo',                      27.53, -99.49),
  ('CPKC', 'Meridian',                    32.36, -88.70),
  ('CPKC', 'Nahant',                      41.55, -90.65),   -- Davenport, IA
  ('CPKC', 'New Orleans',                 29.95, -90.07),
  ('CPKC', 'Shreveport',                  32.53, -93.75),
  ('CPKC', 'St Paul',                     44.95, -93.09),
  ('CSX',  'Baltimore, MD',               39.29, -76.61),
  ('CSX',  'Chicago, IL',                 41.65, -87.63),   -- Barr Yard
  ('CSX',  'Cincinnati, OH',              39.11, -84.53),   -- Queensgate
  ('CSX',  'Indianapolis, IN',            39.76, -86.40),   -- Avon
  ('CSX',  'Jacksonville, FL',            30.33, -81.66),
  ('CSX',  'Louisville, KY',              38.20, -85.76),
  ('CSX',  'Nashville, TN',               36.16, -86.78),   -- Radnor
  ('CSX',  'Rocky Mount, NC',             35.94, -77.79),
  ('CSX',  'Selkirk, NY',                 42.54, -73.80),
  ('CSX',  'Toledo, OH',                  41.65, -83.54),
  ('CSX',  'Waycross, GA',                31.21, -82.35),
  ('NS',   'ALLENTOWN',                   40.60, -75.47),
  ('NS',   'ATLANTA',                     33.80, -84.45),   -- Inman
  ('NS',   'BELLEVUE',                    41.27, -82.84),   -- Bellevue, OH
  ('NS',   'BIRMINGHAM',                  33.52, -86.80),
  ('NS',   'CHATTANOOGA',                 35.01, -85.25),
  ('NS',   'CONWAY',                      40.66, -80.24),   -- Conway, PA
  ('NS',   'DECATUR',                     39.84, -88.95),   -- Decatur, IL
  ('NS',   'ELKHART',                     41.68, -85.98),
  ('NS',   'HARRISBURG',                  40.27, -76.88),
  ('NS',   'LINWOOD',                     35.76, -80.36),   -- Linwood, NC
  ('NS',   'MACON',                       32.84, -83.63),
  ('NS',   'ROANOKE',                     37.27, -79.94),
  ('UP',   'Chicago (Proviso), IL',       41.89, -87.87),
  ('UP',   'Fort Worth, TX',              32.73, -97.38),   -- Davidson
  ('UP',   'Houston (Englewood), TX',     29.78, -95.31),
  ('UP',   'Livonia, LA',                 30.56, -91.55),
  ('UP',   'North Little Rock, AR',       34.77, -92.27),
  ('UP',   'North Platte East, NE',       41.13, -100.74),  -- Bailey Yard
  ('UP',   'North Platte West, NE',       41.14, -100.82),
  ('UP',   'Pine Bluff, AR',              34.23, -92.00),
  ('UP',   'Roseville, CA',               38.75, -121.29),
  ('UP',   'Santa Teresa',                31.86, -106.65),  -- Santa Teresa, NM
  ('UP',   'West Colton, CA',             34.06, -117.36)
ON CONFLICT (railroad, terminal) DO UPDATE SET lat = EXCLUDED.lat, lon = EXCLUDED.lon;
