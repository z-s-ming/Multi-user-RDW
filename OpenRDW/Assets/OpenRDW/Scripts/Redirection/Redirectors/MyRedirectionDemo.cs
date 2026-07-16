using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/*
 This is a demo redirector that only applies curvature gain with a cap on the maximum rotation per second.
 It serves as a simple example of how to create a custom redirector by inheriting from the Redirector base class.
*/
public class MyRedirectionDemo : Redirector
{

    private const float CURVATURE_GAIN_CAP_DEGREES_PER_SECOND = 15;  // degrees per second

    public override void InjectRedirection()
    {
        var deltaTime = redirectionManager.GetDeltaTime();
        var maxRotationFromCurvatureGain = CURVATURE_GAIN_CAP_DEGREES_PER_SECOND * deltaTime;

        //apply curvature
        InjectCurvature(maxRotationFromCurvatureGain);
    }
}
