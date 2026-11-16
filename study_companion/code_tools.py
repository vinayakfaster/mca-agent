import os
import ast
import json

def scan_codebase(directory_path: str) -> str:
    """1. Traverse directory, 2. Identify file types, 3. Extract imports, 4. Return structure tree"""
    if not os.path.exists(directory_path):
        return f"Directory '{directory_path}' not found."
    
    structure = []
    py_files = 0
    other_files = 0
    
    for root, dirs, files in os.walk(directory_path):
        # Skip hidden folders and virtual envs
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'venv', 'env', 'node_modules']]
        
        level = root.replace(directory_path, '').count(os.sep)
        indent = ' ' * 4 * level
        structure.append(f"{indent}{os.path.basename(root)}/")
        
        for file in files:
            if file.endswith('.py'):
                py_files += 1
                file_path = os.path.join(root, file)
                
                # Extract imports
                imports = []
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        tree = ast.parse(f.read())
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for n in node.names:
                                imports.append(n.name)
                        elif isinstance(node, ast.ImportFrom):
                            imports.append(node.module)
                except Exception:
                    pass
                
                import_str = f" [Imports: {', '.join(set(imports))}]" if imports else ""
                structure.append(f"{indent}    {file}{import_str}")
            else:
                other_files += 1
                structure.append(f"{indent}    {file}")
    
    summary = f"✅ Codebase Scanned!\n\n**Python Files:** {py_files}\n**Other Files:** {other_files}\n\n**Structure:**\n" + "\n".join(structure[:100])
    if len(structure) > 100:
        summary += f"\n... and {len(structure) - 100} more items"
    return summary


def analyze_functions(file_path: str) -> str:
    """1. Parse AST, 2. Extract names + params, 3. Detect docstrings, 4. Return function map"""
    if not os.path.exists(file_path) or not file_path.endswith('.py'):
        return "Please provide a valid Python file path."
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read())
        
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = [a.arg for a in node.args.args]
                has_doc = ast.get_docstring(node) is not None
                functions.append({
                    "name": node.name,
                    "args": args,
                    "has_docstring": has_doc,
                    "line": node.lineno
                })
        
        if not functions:
            return "No functions found in this file."
        
        result = f"✅ Found {len(functions)} functions in `{os.path.basename(file_path)}`:\n\n"
        for fn in functions:
            doc_status = "✅ Has docstring" if fn["has_docstring"] else "❌ Missing docstring"
            result += f"- **{fn['name']}**({', '.join(fn['args'])}) - Line {fn['line']} - {doc_status}\n"
        
        return result
    except Exception as e:
        return f"Error analyzing file: {str(e)}"


def generate_readme(directory_path: str) -> str:
    """1. Collect metadata, 2. Write install section, 3. Usage examples, 4. API docs -> README.md"""
    if not os.path.exists(directory_path):
        return f"Directory '{directory_path}' not found."
    
    readme_content = f"# Project Documentation\n\nGenerated automatically for `{os.path.basename(directory_path)}`.\n\n"
    readme_content += "## Installation\n\n```bash\npip install -r requirements.txt\n```\n\n"
    readme_content += "## Usage\n\n```python\n# Example usage\nfrom main import app\napp.run()\n```\n\n"
    readme_content += "## API / Functions\n\n"
    
    found_any = False
    for root, dirs, files in os.walk(directory_path):
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['__pycache__', 'venv', 'env', 'node_modules']]
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        tree = ast.parse(f.read())
                    
                    file_functions = []
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            doc = ast.get_docstring(node) or "No description provided."
                            file_functions.append((node.name, doc))
                    
                    if file_functions:
                        found_any = True
                        rel_path = os.path.relpath(file_path, directory_path)
                        readme_content += f"### `{rel_path}`\n\n"
                        for name, doc in file_functions:
                            readme_content += f"#### `{name}()`\n{doc}\n\n"
                except Exception:
                    continue
    
    if not found_any:
        readme_content += "No functions found to document.\n"
    
    # Save to file
    output_path = os.path.join(directory_path, "README_generated.md")
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(readme_content)
    
    return f"✅ README Generated!\n\nSaved to: `{output_path}`\n\n**Preview:**\n```markdown\n{readme_content[:1500]}\n```"


def write_docstrings(file_path: str) -> str:
    """1. Find missing docstrings, 2. Generate Google-style, 3. Return updated code"""
    if not os.path.exists(file_path) or not file_path.endswith('.py'):
        return "Please provide a valid Python file path."
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
        
        tree = ast.parse(source)
        lines = source.split('\n')
        insertions = []  # (line_number, docstring_text)
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if ast.get_docstring(node) is None:
                    # Generate Google-style docstring
                    args = [a.arg for a in node.args.args]
                    args_doc = "\n".join([f"        {arg}: Description of {arg}." for arg in args]) if args else "        None"
                    
                    docstring = f'''    """
    {node.name.replace('_', ' ').title()}.

    Args:
{args_doc}

    Returns:
        Description of return value.
    """
'''
                    insertions.append((node.body[0].lineno - 1, docstring))
        
        if not insertions:
            return "✅ All functions already have docstrings! No changes needed."
        
        # Insert from bottom to top so line numbers don't shift
        for line_num, docstring in sorted(insertions, reverse=True):
            lines.insert(line_num, docstring)
        
        updated_code = '\n'.join(lines)
        
        # Optionally save to a new file
        output_path = file_path.replace('.py', '_documented.py')
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(updated_code)
        
        return f"✅ Docstrings Added!\n\n**Added {len(insertions)} docstrings.**\nSaved to: `{output_path}`\n\n**Preview (first 1000 chars):**\n```python\n{updated_code[:1000]}\n```"
    except Exception as e:
        return f"Error writing docstrings: {str(e)}"