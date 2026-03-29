import matplotlib.pyplot as plt

# Parameters
window_size = 100
candles = []
df = pd.DataFrame()

def plotwith(data, symbol, interval="1m"):
    # Initialize Matplotlib
    fig, ax = plt.subplots()
    line, = ax.plot([], [], label='Close Price')
    scatter = ax.scatter([], [], color='green', label='Continuation Signal')
    ax.set_title(f'{symbol.upper()} - {interval.upper()} RIMC Detection')
    ax.set_xlabel('Time')
    ax.set_ylabel('Price')
    ax.legend()
    plt.xticks(rotation=45)

# Update plot data
def update_plot(frame):
    if df.empty:
        return line, scatter

    line.set_data(df['timestamp'], df['Close'])
    ax.relim()
    ax.autoscale_view()

    # Scatter continuation entries
    entry_signals = df[df['continuation']]
    scatter.set_offsets(list(zip(entry_signals['timestamp'], entry_signals['Close'])))

    return line, scatter