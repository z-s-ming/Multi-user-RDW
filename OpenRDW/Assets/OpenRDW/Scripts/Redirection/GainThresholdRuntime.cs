using UnityEngine;

public enum GainThresholdControlMode
{
    Fixed,
    Dynamic
}

public enum RedirectionRuntimeState
{
    NoRedirection,
    RedirectedWalking
}

public interface IGainThresholdScaleProvider
{
    float GetThresholdScale();
}

public class FixedGainThresholdScaleProvider : IGainThresholdScaleProvider
{
    private readonly float thresholdScale;

    public FixedGainThresholdScaleProvider(float thresholdScale)
    {
        this.thresholdScale = Mathf.Clamp01(thresholdScale);
    }

    public float GetThresholdScale()
    {
        return thresholdScale;
    }
}

public class DynamicGainThresholdScaleProvider : IGainThresholdScaleProvider
{
    private readonly FixedGainThresholdScaleProvider fallbackProvider;

    public DynamicGainThresholdScaleProvider(float fallbackThresholdScale)
    {
        fallbackProvider = new FixedGainThresholdScaleProvider(fallbackThresholdScale);
    }

    public float GetThresholdScale()
    {
        return fallbackProvider.GetThresholdScale();
    }
}
