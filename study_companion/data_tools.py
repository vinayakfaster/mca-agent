import os
import pandas as pd
import duckdb
import matplotlib.pyplot as plt
import seaborn as sns
import json
from typing import Optional

# Global variable to hold the current DataFrame (for demo purposes)
_current_df = None

def load_data(file_path: str) -> str:
    """1. Load CSV / Excel"""
    global _current_df
    try:
        if file_path.endswith('.csv'):
            _current_df = pd.read_csv(file_path)
        elif file_path.endswith(('.xls', '.xlsx')):
            _current_df = pd.read_excel(file_path)
        else:
            return "Unsupported file format. Please upload CSV or Excel."
        
        # 2. Detect types & schema
        schema = _current_df.dtypes.to_dict()
        schema_str = "\n".join([f"- {col}: {dtype}" for col, dtype in schema.items()])
        
        # 3. Return DataFrame preview
        preview = _current_df.head(5).to_string()
        
        return f"✅ Data Loaded Successfully!\n\n**Shape:** {_current_df.shape[0]} rows, {_current_df.shape[1]} columns\n\n**Schema:**\n{schema_str}\n\n**Preview:**\n{preview}"
    except Exception as e:
        return f"Error loading data: {str(e)}"

def clean_data() -> str:
    """1. Handle missing values, 2. Remove duplicates, 3. Standardize columns"""
    global _current_df
    if _current_df is None:
        return "No data loaded. Please load data first."
    
    try:
        original_shape = _current_df.shape
        
        # Standardize column names (lowercase, replace spaces with underscores)
        _current_df.columns = [c.strip().lower().replace(' ', '_') for c in _current_df.columns]
        
        # Handle missing values (fill numeric with mean, categorical with mode, or drop)
        missing_before = _current_df.isnull().sum().sum()
        for col in _current_df.columns:
            if _current_df[col].dtype in ['int64', 'float64']:
                _current_df[col] = _current_df[col].fillna(_current_df[col].mean())
            else:
                _current_df[col] = _current_df[col].fillna(_current_df[col].mode()[0] if not _current_df[col].mode().empty else "Unknown")
        
        # Remove duplicates
        _current_df = _current_df.drop_duplicates()
        
        # 4. Return cleaned data preview
        new_shape = _current_df.shape
        return f"✅ Data Cleaned!\n\n**Missing values handled:** {missing_before}\n**Duplicates removed:** {original_shape[0] - new_shape[0]}\n**New Shape:** {new_shape[0]} rows, {new_shape[1]} columns\n\n**Preview:**\n{_current_df.head(5).to_string()}"
    except Exception as e:
        return f"Error cleaning data: {str(e)}"

def run_sql_query(query: str) -> str:
    """1. Parse SQL, 2. Execute on DuckDB, 3. Return results"""
    global _current_df
    if _current_df is None:
        return "No data loaded. Please load data first."
    
    try:
        # Register dataframe to DuckDB
        con = duckdb.connect(database=':memory:')
        con.register('data', _current_df)
        
        # Execute query
        result_df = con.execute(query).fetchdf()
        con.close()
        
        if result_df.empty:
            return "Query executed successfully, but returned no results."
        
        # Return results as string (limited to 20 rows for display)
        return f"✅ SQL Query Executed!\n\n**Results ({len(result_df)} rows):**\n{result_df.head(20).to_string()}"
    except Exception as e:
        return f"SQL Error: {str(e)}"

def generate_charts() -> str:
    """1. Identify viz columns, 2. matplotlib/seaborn, 3. Save PNG -> return path"""
    global _current_df
    if _current_df is None:
        return "No data loaded. Please load data first."
    
    try:
        # Create output directory
        os.makedirs("generated_charts", exist_ok=True)
        chart_paths = []
        
        # Identify numeric and categorical columns
        numeric_cols = _current_df.select_dtypes(include=['int64', 'float64']).columns.tolist()
        cat_cols = _current_df.select_dtypes(include=['object', 'category']).columns.tolist()
        
        # 1. Histogram for first numeric column
        if numeric_cols:
            plt.figure(figsize=(8, 5))
            sns.histplot(_current_df[numeric_cols[0]], kde=True)
            plt.title(f"Distribution of {numeric_cols[0]}")
            path1 = "generated_charts/histogram.png"
            plt.savefig(path1)
            plt.close()
            chart_paths.append(f"- Histogram of {numeric_cols[0]}: `/{path1}`")
        
        # 2. Bar chart for first categorical column
        if cat_cols:
            plt.figure(figsize=(8, 5))
            top_cats = _current_df[cat_cols[0]].value_counts().head(10)
            sns.barplot(x=top_cats.index, y=top_cats.values)
            plt.title(f"Top 10 {cat_cols[0]}")
            plt.xticks(rotation=45)
            path2 = "generated_charts/bar_chart.png"
            plt.savefig(path2)
            plt.close()
            chart_paths.append(f"- Bar chart of {cat_cols[0]}: `/{path2}`")
        
        # 3. Correlation heatmap if 2+ numeric columns
        if len(numeric_cols) >= 2:
            plt.figure(figsize=(10, 8))
            sns.heatmap(_current_df[numeric_cols].corr(), annot=True, cmap='coolwarm')
            plt.title("Correlation Heatmap")
            path3 = "generated_charts/heatmap.png"
            plt.savefig(path3)
            plt.close()
            chart_paths.append(f"- Correlation Heatmap: `/{path3}`")
            
        if not chart_paths:
            return "Not enough numeric/categorical data to generate charts."
            
        return "✅ Charts Generated!\n\n" + "\n".join(chart_paths)
    except Exception as e:
        return f"Error generating charts: {str(e)}"

def statistical_analysis() -> str:
    """1. mean/median/mode, 2. Correlation matrix, 3. Outlier detection"""
    global _current_df
    if _current_df is None:
        return "No data loaded. Please load data first."
    
    try:
        numeric_df = _current_df.select_dtypes(include=['int64', 'float64'])
        if numeric_df.empty:
            return "No numeric columns available for statistical analysis."
        
        # 1. Mean, Median, Mode
        stats = numeric_df.describe().T[['mean', '50%', 'std', 'min', 'max']]
        stats.rename(columns={'50%': 'median'}, inplace=True)
        
        # 2. Correlation Matrix
        corr = numeric_df.corr().round(2)
        
        # 3. Outlier detection (IQR method)
        outliers = {}
        for col in numeric_df.columns:
            Q1 = numeric_df[col].quantile(0.25)
            Q3 = numeric_df[col].quantile(0.75)
            IQR = Q3 - Q1
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            count = len(numeric_df[(numeric_df[col] < lower_bound) | (numeric_df[col] > upper_bound)])
            if count > 0:
                outliers[col] = count
        
        outlier_str = "\n".join([f"- {k}: {v} outliers" for k, v in outliers.items()]) if outliers else "None detected."
        
        return f"✅ Statistical Analysis\n\n**Basic Stats:**\n{stats.to_string()}\n\n**Correlation Matrix:**\n{corr.to_string()}\n\n**Outliers (IQR Method):**\n{outlier_str}"
    except Exception as e:
        return f"Error in statistical analysis: {str(e)}"