def log(msg):
    """
    Log a message to the console with a timestamp.
    :param msg: The message to log.
    """
    from datetime import datetime

    # Get the current time
    now = datetime.now()

    # Format the time as HH:MM:SS
    current_time = now.strftime("%H:%M:%S")

    # Print the message with the timestamp
    print(f"[{current_time}] {msg}")