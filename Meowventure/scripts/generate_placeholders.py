from PIL import Image, ImageDraw, ImageFont
import os
import json

def create_placeholder_image(name, output_path):
    """Create a simple placeholder image with just the cat name"""
    # Create a new image with a white background
    width = 400
    height = 400
    image = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(image)
    
    try:
        # Try to load a font, fall back to default if not available
        font = ImageFont.truetype("arial.ttf", 40)
    except:
        font = ImageFont.load_default()

    # Draw a light gray border
    draw.rectangle([10, 10, width-10, height-10], outline='gray', width=2)
    
    # Draw the cat name
    text_width = draw.textlength(name, font=font)
    text_x = (width - text_width) // 2
    draw.text((text_x, height//2), name, fill='black', font=font)
    
    # Save the image
    image.save(output_path)

def main():
    # Read cats from the JSON file with UTF-8 encoding
    with open("data/cats.json", "r", encoding='utf-8') as f:
        cats_data = json.load(f)
    
    # Create images directory if it doesn't exist
    os.makedirs("data/images", exist_ok=True)
    
    # Generate placeholder for each cat
    for cat in cats_data["cats"]:
        output_path = f"data/images/{cat['id']}_cat.png"
        create_placeholder_image(cat['name'], output_path)
        print(f"Created placeholder for {cat['name']}")

if __name__ == "__main__":
    main()
